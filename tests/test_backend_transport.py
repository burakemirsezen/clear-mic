import json,os,queue,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.data=tempfile.TemporaryDirectory();env=os.environ.copy();env['CLEARMIC_DATA_DIR']=self.data.name
        self.process=subprocess.Popen([sys.executable,'-u',str(ROOT/'backend.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        self.messages=queue.Queue()
        threading.Thread(target=lambda:[self.messages.put(json.loads(line)) for line in self.process.stdout],daemon=True).start()
        self.until(lambda m:m.get('event')=='ready')
    def until(self,predicate):
        for i in range(100):
            message=self.messages.get(timeout=10)
            if predicate(message):return message
        self.fail('Expected response was not received')
    def request(self,id,action,value=None):
        self.process.stdin.write(json.dumps({'id':id,'action':action,'value':value})+'\n');self.process.stdin.flush()
        return self.until(lambda m:m.get('id')==id)
    def tearDown(self):
        if self.process.poll() is None:self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait();self.fail('Audio child did not exit on parent disconnect')
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            if not stream.closed:stream.close()
        self.data.cleanup()
    def test_settings_persist_across_control_channel(self):
        result=self.request(1,'configure',{'voice':{'output_db':-3},'preset':'Custom'})
        self.assertEqual(result['result']['voice']['output_db'],-3)
        self.assertEqual(self.request(2,'snapshot')['result']['settings']['voice']['output_db'],-3)
        stored=json.loads((Path(self.data.name)/'settings.json').read_text());self.assertEqual(stored['voice']['output_db'],-3)
    def test_invalid_command_does_not_break_subsequent_requests(self):
        self.assertIn('error',self.request(1,'launch_arbitrary_process'))
        self.assertIn('settings',self.request(2,'snapshot')['result'])
    def test_invalid_voice_settings_leave_previous_configuration_intact(self):
        self.assertIn('error',self.request(1,'configure',{'voice':{'ratio':900}}))
        self.assertEqual(self.request(2,'snapshot')['result']['settings']['voice']['ratio'],2)
