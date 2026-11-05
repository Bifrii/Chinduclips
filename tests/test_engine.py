import unittest, sys, tempfile, json, subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from ranking import candidates,make_srt
import server
class EngineTests(unittest.TestCase):
    def test_ranking_and_overlap(self):
        seg=[{'start':i*5,'end':i*5+5,'text':('Pourquoi cette erreur change tout ?' if i%6==0 else 'Une idée claire avec un exemple concret.')} for i in range(24)]
        clips=candidates(seg,20,40,6)
        self.assertGreater(len(clips),1)
        for c in clips:self.assertTrue(20<=c['end']-c['start']<=40)
        for i,c in enumerate(clips):
            for p in clips[i+1:]:self.assertLessEqual(max(0,min(c['end'],p['end'])-max(c['start'],p['start']))/min(c['end']-c['start'],p['end']-p['start']),.35)
    def test_srt_clips_and_escapes(self):
        self.assertEqual(make_srt([{'start':8,'end':12,'text':'<b>Bonjour</b> {\\pos(0,0)}'}],10,11),'1\n00:00:00,000 --> 00:00:01,000\nBonjour\n')
    def test_real_ffmpeg_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            server.DATA=Path(tmp);jid='a'*32;folder=server.DATA/jid;folder.mkdir()
            subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=15:d=3','-f','lavfi','-i','sine=frequency=220:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(folder/'source.mp4')],capture_output=True,check=True)
            server.save({'id':jid,'duration':3,'status':'done'})
            out=server.render(jid,{'start':.5,'end':2,'aspect':'9:16','style':'bold','subtitles':True,'cues':[{'start':0,'end':3,'text':'Bonjour Kinshasa !'}]})
            data=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_format','-show_streams','-of','json',str(folder/out['file'])]))
            v=next(s for s in data['streams'] if s['codec_type']=='video')
            self.assertEqual((v['width'],v['height']),(720,1280))
            self.assertAlmostEqual(float(data['format']['duration']),1.5,delta=.15)
            self.assertIn('Bonjour', (folder/out['srt']).read_text())
    def test_reject_invalid_id(self):
        with self.assertRaises(ValueError):server.read_job('../../etc/passwd')
if __name__=='__main__':unittest.main()
