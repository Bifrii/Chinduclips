"""Chindu Clips: single-owner video worker. Run behind HTTPS on a VPS."""
import os, json, uuid, time, shutil, subprocess, threading, secrets, re, logging
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
from ranking import candidates, make_srt

ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv('DATA_DIR',str(ROOT/'data'))).resolve(); DATA.mkdir(parents=True,exist_ok=True)
WEB=ROOT/'web'
KEY=os.getenv('CLIP_API_KEY','')
ALLOWED=os.getenv('ALLOWED_ORIGINS','https://chindu-clips-emery.savorysnail2048.chatgpt.site,http://localhost:8080').split(',')
POOL=ThreadPoolExecutor(max_workers=1)
MODEL=None
MAX_BYTES=400*1024*1024

def run(args,timeout=1800):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if p.returncode:
        detail = p.stderr or ''
        logging.error('%s failed: %s', Path(args[0]).name, re.sub(r'https?://\S+', '[URL]', detail[-4000:]))
        if Path(args[0]).name == 'yt-dlp':
            lower = detail.lower()
            if 'private video' in lower:
                raise RuntimeError('YouTube indique que cette vidéo est privée. Importez un fichier auquel vous avez accès.')
            if 'this video is not available' in lower or 'video unavailable' in lower or 'has been removed' in lower:
                raise RuntimeError('YouTube indique que cette vidéo est indisponible. Vérifiez le lien exact ou importez votre fichier.')
            if 'sign in' in lower or 'confirm you' in lower:
                raise RuntimeError('YouTube demande une connexion ou une vérification et bloque la récupération. Importez votre fichier vidéo.')
            if 'requested format is not available' in lower:
                raise RuntimeError('Le format vidéo demandé est indisponible. Essayez une autre vidéo ou importez votre fichier.')
            raise RuntimeError('Échec de récupération YouTube. Vérifiez le réseau et consultez les journaux Docker pour le détail.')
        raise RuntimeError('Le traitement FFmpeg a échoué. Vérifiez le fichier vidéo ; le détail est dans les journaux Docker.')
    return p.stdout

def read_job(jid):
    if not jid or not all(c in '0123456789abcdef' for c in jid) or len(jid)!=32: raise ValueError('Projet inconnu.')
    return json.loads((DATA/jid/'job.json').read_text())

def save(j):
    folder=DATA/j['id']; folder.mkdir(exist_ok=True)
    temp=folder/('job-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(j,ensure_ascii=False));temp.replace(folder/'job.json')

def process(jid):
    global MODEL
    j=read_job(jid); folder=DATA/jid
    try:
        j.update(status='processing',stage='Récupération de la vidéo',progress=8);save(j)
        source=folder/'source.mp4'
        if j.get('url'):
            # Only YouTube, no arbitrary URL fetch, redirects or playlists. Proxy-free execution.
            run(['yt-dlp','--js-runtimes','node','--ignore-config','--no-playlist','--max-filesize','400M','--match-filter','duration <= 3600','--socket-timeout','30','--retries','2','--format','bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]','--merge-output-format','mp4','--output',str(source),'--',j['url']])
        if not source.exists():raise RuntimeError('Vidéo indisponible, privée, trop longue ou supérieure à 400 Mo. Importez votre fichier si YouTube bloque le téléchargement.')
        probe=json.loads(run(['ffprobe','-v','quiet','-show_format','-show_streams','-of','json',str(source)],120))
        duration=float(probe['format']['duration'])
        if duration>3600 or source.stat().st_size>MAX_BYTES:raise RuntimeError('Limite : une heure et 400 Mo par vidéo.')
        if not any(s.get('codec_type')=='audio' for s in probe['streams']): raise RuntimeError('La vidéo ne contient pas de piste audio à transcrire.')
        j.update(duration=duration,stage='Transcription locale de la parole',progress=30);save(j)
        audio=folder/'audio.wav'
        run(['ffmpeg','-y','-i',str(source),'-vn','-ac','1','-ar','16000',str(audio)])
        from faster_whisper import WhisperModel
        if MODEL is None:MODEL=WhisperModel(os.getenv('WHISPER_MODEL','small'),device='cpu',compute_type='int8')
        segments,info=MODEL.transcribe(str(audio),language=None if j['language']=='auto' else j['language'],vad_filter=True,word_timestamps=True)
        transcript=[]
        for s in segments:
            # Short word groups keep mobile subtitles legible.
            words=s.words or []
            if words:
                for a in range(0,len(words),6):
                    group=words[a:a+6]
                    transcript.append({'start':round(group[0].start,2),'end':round(group[-1].end,2),'text':''.join(w.word for w in group).strip()})
            else:transcript.append({'start':s.start,'end':s.end,'text':s.text.strip()})
        j.update(stage='Sélection des passages',progress=85);save(j)
        clips=candidates(transcript,j['min_duration'],j['max_duration'],j['count'])
        if not clips:raise RuntimeError('Aucun passage parlé exploitable détecté dans cette vidéo.')
        j.update(status='done',progress=100,stage='Extraits prêts',clips=clips,transcript=transcript,detected_language=info.language);save(j)
        audio.unlink(missing_ok=True)
    except Exception as e:
        j.update(status='error',error=str(e) if isinstance(e,RuntimeError) else 'Le moteur a rencontré une erreur. Vérifiez les dépendances, la mémoire disponible et le modèle de transcription.');save(j)

def render(jid, options):
    j=read_job(jid);folder=DATA/jid
    start=float(options['start']);end=float(options['end'])
    if not(0<=start<end<=j['duration']+.1) or end-start>180:raise ValueError('Coupe invalide (maximum 180 secondes).')
    aspect=options.get('aspect','9:16');style=options.get('style','bold')
    if aspect not in ('9:16','1:1','16:9') or style not in ('bold','clean','yellow'):raise ValueError('Format invalide.')
    eid=uuid.uuid4().hex
    srt=folder/(eid+'.srt');srt.write_text(make_srt(options.get('cues',[]),start,end),encoding='utf-8')
    dims={'9:16':(720,1280),'1:1':(720,720),'16:9':(1280,720)};w,h=dims[aspect]
    # Blurred background preserves the complete picture and avoids cutting faces.
    filt=f'[0:v]split=2[bg][fg];[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[back];[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[front];[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1[base]'
    if options.get('subtitles',True) and srt.stat().st_size:
        color='&H0000FFFF' if style=='yellow' else '&H00FFFFFF'
        ass=f'FontName=DejaVu Sans,FontSize={25 if aspect=="9:16" else 22},PrimaryColour={color},OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=90,Bold={-1 if style!="clean" else 0}'
        filt+=f";[base]subtitles=filename='{srt}':force_style='{ass}'[out]"
    else:filt+=';[base]null[out]'
    output=folder/(eid+'.mp4')
    run(['ffmpeg','-y','-ss',str(start),'-i',str(folder/'source.mp4'),'-t',str(end-start),'-filter_complex',filt,'-map','[out]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','22','-c:a','aac','-b:a','128k','-movflags','+faststart',str(output)])
    return {'id':eid,'file':eid+'.mp4','srt':eid+'.srt'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,obj):
        body=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.cors();self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def cors(self):
        origin=self.headers.get('Origin','')
        if origin in ALLOWED:self.send_header('Access-Control-Allow-Origin',origin)
        self.send_header('Vary','Origin');self.send_header('Access-Control-Allow-Headers','Authorization,Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,DELETE,OPTIONS')
    def auth(self):return bool(KEY) and secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+KEY)
    def do_OPTIONS(self):self.send_response(204);self.cors();self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        if not path.startswith('/api/'):
            name='index.html' if path=='/' else path.lstrip('/')
            file=(WEB/name).resolve()
            if not file.is_relative_to(WEB.resolve()) or not file.is_file():return self.send(404,{'error':'Page introuvable.'})
            return self.file(file)
        if not self.auth():return self.send(401,{'error':'Clé du moteur invalide.'})
        try:
            if path=='/api/health':return self.send(200,{'ok':True,'engine':'Chindu Clips','version':'1.0','model':os.getenv('WHISPER_MODEL','small')})
            if path=='/api/jobs':
                jobs=[]
                for f in DATA.glob('*/job.json'):
                    j=json.loads(f.read_text());j.pop('transcript',None);jobs.append(j)
                return self.send(200,sorted(jobs,key=lambda j:j['created'],reverse=True))
            parts=path.strip('/').split('/')
            if len(parts)==3 and parts[:2]==['api','jobs']:return self.send(200,read_job(parts[2]))
            if len(parts)==4 and parts[:2]==['api','files']:
                read_job(parts[2]);name=parts[3]
                if not (name=='source.mp4' or (len(name.split('.')[0])==32 and all(c in '0123456789abcdef' for c in name.split('.')[0]) and name.endswith(('.mp4','.srt')))):return self.send(400,{'error':'Fichier invalide.'})
                return self.file(DATA/parts[2]/name)
            return self.send(404,{'error':'Route inconnue.'})
        except (ValueError,FileNotFoundError):return self.send(404,{'error':'Projet introuvable.'})
    def file(self,file):
        import mimetypes
        if not file.exists():return self.send(404,{'error':'Fichier introuvable.'})
        self.send_response(200);self.cors();self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(file.stat().st_size));self.end_headers()
        with file.open('rb') as f:shutil.copyfileobj(f,self.wfile)
    def do_POST(self):
        if not self.auth():return self.send(401,{'error':'Clé du moteur invalide.'})
        try:
            url=urlparse(self.path);path=url.path;length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>MAX_BYTES:return self.send(413,{'error':'Fichier vide ou supérieur à 400 Mo.'})
            if path=='/api/upload':
                if not self.headers.get('Content-Type','').startswith('video/'):return self.send(400,{'error':'Un fichier vidéo est requis.'})
                if sum(1 for f in DATA.glob('*/job.json') if json.loads(f.read_text()).get('status') in ('queued','processing'))>=3:return self.send(429,{'error':'Trois vidéos sont déjà en attente.'})
                jid=uuid.uuid4().hex;folder=DATA/jid;folder.mkdir()
                with (folder/'source.mp4').open('wb') as f:
                    remaining=length
                    while remaining:
                        chunk=self.rfile.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('Envoi interrompu.')
                        f.write(chunk);remaining-=len(chunk)
                q=parse_qs(url.query);data={k:v[0] for k,v in q.items()};data['title']=data.get('name','Vidéo importée')[:160];data['url']=None
            elif path=='/api/jobs':
                if length>20000:return self.send(413,{'error':'Requête trop volumineuse.'})
                data=json.loads(self.rfile.read(length));p=urlparse(data.get('url',''))
                if p.scheme!='https' or p.hostname not in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be') or p.username or p.password or p.port not in (None,443):raise ValueError('Collez un lien HTTPS YouTube valide.')
                # Canonicalize to a video ID to discard playlist, redirect and tracking parameters.
                q=parse_qs(p.query);video_id=(q.get('v') or [''])[0] if p.path=='/watch' else (p.path.strip('/').split('/')[-1] if p.hostname=='youtu.be' or p.path.startswith(('/shorts/','/live/')) else '')
                import re
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):raise ValueError('Lien vidéo YouTube invalide.')
                data['url']='https://www.youtube.com/watch?v='+video_id
                if sum(1 for f in DATA.glob('*/job.json') if json.loads(f.read_text()).get('status') in ('queued','processing'))>=3:return self.send(429,{'error':'Trois vidéos sont déjà en attente.'})
                jid=uuid.uuid4().hex
            elif path.startswith('/api/export/'):
                if length>300000:return self.send(413,{'error':'Sous-titres trop volumineux.'})
                data=json.loads(self.rfile.read(length));jid=path.split('/')[-1]
                if read_job(jid)['status']!='done':raise ValueError('Analyse non terminée.')
                return self.send(200,render(jid,data))
            else:return self.send(404,{'error':'Route inconnue.'})
            minimum=max(5,min(90,int(data.get('min_duration',20))));maximum=max(minimum,min(120,int(data.get('max_duration',60))));lang=data.get('language','auto')
            if lang not in ('auto','fr','en','es','pt','sw'):raise ValueError('Langue invalide.')
            j={'id':jid,'title':data.get('title','Vidéo YouTube'),'url':data.get('url'),'created':time.time(),'status':'queued','stage':'En attente','progress':0,'language':lang,'min_duration':minimum,'max_duration':maximum,'count':max(1,min(12,int(data.get('count',6)))),'clips':[]}
            save(j);POOL.submit(process,jid);return self.send(202,j)
        except (ValueError,KeyError,TypeError):return self.send(400,{'error':'Paramètres invalides. Vérifiez le lien et les durées.'})
        except FileNotFoundError:return self.send(404,{'error':'Projet ou FFmpeg introuvable.'})
        except Exception:return self.send(500,{'error':'Le traitement a échoué. Vérifiez le moteur et réessayez.'})
    def do_DELETE(self):
        if not self.auth():return self.send(401,{'error':'Clé invalide.'})
        try:
            jid=urlparse(self.path).path.split('/')[-1];j=read_job(jid)
            if j['status'] in ('queued','processing'):return self.send(409,{'error':'Attendez la fin du traitement.'})
            shutil.rmtree(DATA/jid);return self.send(200,{'ok':True})
        except Exception:return self.send(404,{'error':'Projet introuvable.'})

if __name__=='__main__':
    if len(KEY)<24:raise SystemExit('Définissez CLIP_API_KEY avec au moins 24 caractères aléatoires.')
    # Jobs interrupted by restart must never remain pending forever.
    for f in DATA.glob('*/job.json'):
        j=json.loads(f.read_text())
        if j['status'] in ('queued','processing'):j.update(status='error',error='Moteur redémarré pendant le traitement. Relancez cette vidéo.');save(j)
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
