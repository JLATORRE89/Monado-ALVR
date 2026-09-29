import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tablet_audio import desired_links, HeadsetAudioRouter
spec=importlib.util.spec_from_file_location('proximity',ROOT.parents[1]/'scripts/xr-voice.py')
prox=importlib.util.module_from_spec(spec);spec.loader.exec_module(prox)

def node(i,name):return {'id':i,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':name}}}
def port(i,n,d,ch='MONO'):return {'id':i,'type':'PipeWire:Interface:Port','info':{'direction':d,'props':{'node.id':n,'audio.channel':ch}}}
def link(a,b):return {'type':'PipeWire:Interface:Link','info':{'output-port-id':a,'input-port-id':b}}

def graph():
 return [node(1,'ALVR Microphone'),port(11,1,'output'),node(2,'ALVR Audio'),port(21,2,'input'),
         node(3,'ALVR Microphone (tablet-a)'),port(31,3,'output'),node(4,'ALVR Audio (tablet-a)'),port(41,4,'input'),
         node(5,'Game'),port(51,5,'output','FL'),port(52,5,'output','FR'),
         node(6,'Private desktop'),port(61,6,'output')]

class RoutingTests(unittest.TestCase):
 def test_proximity_entry_exit_and_unknown(self):
  g=graph();pos={'primary':(0,0),'tablet-a':(2,0)}
  self.assertEqual(prox.voice_links(g,pos)[0],{(11,41),(31,21)})
  pos['tablet-a']=(3.2,0)
  self.assertEqual(prox.voice_links(g,pos)[0],set())
  g += [link(11,41),link(31,21)]
  self.assertEqual(prox.voice_links(g,pos)[0],{(11,41),(31,21)})
  pos['tablet-a']=(3.6,0)
  self.assertEqual(prox.voice_links(g,pos),(set(),{(11,41),(31,21)}))
  self.assertEqual(prox.voice_links(g,{'primary':(0,0)})[0],set())
 def test_separate_conversations(self):
  g=graph()+[node(7,'ALVR Microphone (quest-b)'),port(71,7,'output'),node(8,'ALVR Audio (quest-b)'),port(81,8,'input')]
  wanted,_=prox.voice_links(g,{'primary':(0,0),'tablet-a':(1,0),'quest-b':(8,0)})
  self.assertEqual(wanted,{(11,41),(31,21)})
 def test_app_sound_excludes_voice_self_and_desktop(self):
  g=graph()+[link(51,21),link(52,21),link(31,21),link(11,41)]
  self.assertEqual(desired_links(g,{'tablet-a'})[0],{(51,41),(52,41)})
  self.assertEqual(desired_links(g,set())[0],set())
  self.assertEqual(desired_links(graph(),{'tablet-a'})[0],set())
 def test_presence_validation(self):
  def pkt(x=1):return prox.PACKET.pack(0x3154464c,b'primary',x,1.66,2,0,0,0,1,0)
  self.assertEqual(prox.read_position(pkt()),('primary',(1,2)))
  self.assertIsNone(prox.read_position(pkt(float('nan'))))
  self.assertIsNone(prox.read_position(b'junk'))
 def test_app_links_removed_when_source_leaves_headset(self):
  import json
  from types import SimpleNamespace
  calls=[];g=graph()+[link(51,21)]
  def run(cmd,**kwargs):
   calls.append(cmd);return SimpleNamespace(returncode=0,stdout=json.dumps(g)+"\n[]")
  router=HeadsetAudioRouter(run);router.sync({'tablet-a'})
  self.assertIn(['pw-link','51','41'],calls)
  g=graph()+[link(51,41)];router.sync({'tablet-a'})
  self.assertIn(['pw-link','-d','51','41'],calls)
if __name__=='__main__':unittest.main()
