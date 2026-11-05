"""Local editorial scoring, deliberately not a prediction of actual virality."""
import re
HOOKS = ['pourquoi', 'comment', 'erreur', 'secret', 'jamais', 'personne', 'imagine', 'vérité', 'attention', 'voici', 'why', 'how', 'mistake', 'secret', 'never', 'truth']
def candidates(segments, minimum=20, maximum=60, count=8):
    results = []
    if not segments:
        return results
    total = segments[-1]['end']
    for i, first in enumerate(segments):
        group=[]
        for seg in segments[i:]:
            if seg['end'] - first['start'] > maximum:
                break
            group.append(seg)
            duration=seg['end']-first['start']
            if duration < minimum:
                continue
            text=' '.join(s['text'].strip() for s in group)
            words=re.findall(r'\w+',text.lower())
            opening=' '.join(words[:22])
            hook=any(w in opening for w in HOOKS)
            question='?' in text[:180]
            complete=bool(re.search(r'[.!?…]$', text.strip()))
            density=min(1,len(words)/max(duration,1)/2.3)
            score=round(min(96, 40+18*hook+8*question+10*complete+12*density+8*min(1,len(set(words))/max(1,len(words)))))
            title=' '.join(text.split()[:11]).strip(' ,;:')
            results.append({'start':round(first['start'],2),'end':round(seg['end'],2),'title':title+('…' if len(words)>11 else ''),'score':score,'reason':('Accroche marquée. ' if hook else '')+('Question qui suscite la curiosité. ' if question else '')+('Phrase complète et rythme oral soutenu.' if complete else 'Passage dense à vérifier dans son contexte.'),'cues':[{'start':s['start'],'end':s['end'],'text':s['text']} for s in group]})
    if not results and total-segments[0]['start']>=3:
        group=[s for s in segments if s['end']-segments[0]['start']<=maximum]
        if group:
            results=[{'start':group[0]['start'],'end':group[-1]['end'],'title':'Extrait court','score':50,'reason':'Vidéo plus courte que la durée demandée.','cues':group}]
    chosen=[]
    for c in sorted(results,key=lambda x:x['score'],reverse=True):
        overlap=any(max(0,min(c['end'],p['end'])-max(c['start'],p['start']))/max(1,min(c['end']-c['start'],p['end']-p['start']))>.35 for p in chosen)
        if not overlap:
            c['id']=str(len(chosen)+1)
            chosen.append(c)
        if len(chosen)>=count:
            break
    return chosen

def srt_time(seconds):
    ms=max(0,round(seconds*1000)); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def make_srt(cues,start,end):
    out=[]
    for cue in cues:
        a=max(start,float(cue['start'])); b=min(end,float(cue['end']))
        if b<=a: continue
        clean=re.sub(r'<[^>]*>|\{[^}]*\}', '', str(cue['text'])).replace('\r',' ').replace('\n',' ').strip()
        if clean: out.append(f'{len(out)+1}\n{srt_time(a-start)} --> {srt_time(b-start)}\n{clean}\n')
    return '\n'.join(out)
