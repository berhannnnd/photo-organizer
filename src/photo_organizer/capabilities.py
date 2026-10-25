"""Role-based configuration, probes and actionable capability discovery."""
import hashlib
import json
import re
import uuid
from urllib.parse import urlparse
from .catalog import connect,writer_lock
from .selection import now
from .errors import CapabilityError

ROLES={
 'vision':('anthropic','openai','ollama','host'),
 'image_text':('ollama','photo-http','host'),
 'description_text':('ollama','openai-text','photo-http','host'),
 'ocr':('tesseract','vision','photo-http','host'),
 'faces':('opencv','photo-http','host'),
}
FIELDS={'protocol','endpoint','model','revision','space','api_key_env','timeout','concurrency','language','detector_path','recognizer_path'}


def configure(state,role,config):
    if role not in ROLES or not isinstance(config,dict) or set(config)-FIELDS:raise ValueError('unknown role or configuration fields')
    protocol=config.get('protocol')
    if protocol not in ROLES[role]:raise CapabilityError('unsupported_protocol','Supported adapters: '+', '.join(ROLES[role]))
    if 'api_key_env' in config and (not isinstance(config['api_key_env'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',config['api_key_env'])):raise ValueError('use a credential environment variable name')
    if protocol in ('anthropic','openai','ollama','openai-text','photo-http'):
        endpoint=config.get('endpoint','');u=urlparse(endpoint)
        local=u.hostname in ('localhost','127.0.0.1','::1')
        if not u.hostname or u.username or u.password or u.query or u.fragment or not (u.scheme=='https' or u.scheme=='http' and local):raise ValueError('use credential-free HTTPS or loopback HTTP endpoint')
        if not isinstance(config.get('model'),str) or not config['model'].strip():raise ValueError('model is required')
        if protocol in ('openai-text','photo-http') and not config.get('revision'):raise ValueError('explicit remote model revision required')
        if role in ('image_text','description_text') and protocol=='photo-http' and not config.get('space'):raise ValueError('embedding space identifier required')
    if protocol=='opencv' and not all(isinstance(config.get(k),str) and config[k] for k in ('detector_path','recognizer_path')):raise ValueError('provide installed detector and recognizer model paths')
    if 'timeout' in config and (type(config['timeout']) not in (int,float) or not 1<=config['timeout']<=300):raise ValueError('timeout must be 1..300 seconds')
    if 'concurrency' in config and (type(config['concurrency']) is not int or not 1<=config['concurrency']<=8):raise ValueError('concurrency must be 1..8')
    if len(json.dumps(config))>5000:raise ValueError('configuration too large')
    revision=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    with writer_lock(state),connect(state) as c:
        old=c.execute('SELECT revision FROM capability_configs WHERE role=?',(role,)).fetchone()
        if not old or old[0]!=revision:
            c.execute('INSERT INTO capability_configs VALUES(?,?,?,?,?,?) ON CONFLICT(role) DO UPDATE SET config=excluded.config,revision=excluded.revision,status=excluded.status,verification=NULL,updated=excluded.updated',(role,json.dumps(config),revision,'configured_unverified',None,now()))
    return {'role':role,'revision':revision,'next_action':'capability-probe','configuration_saved':True}


def get_config(state,role,verified=True):
    with connect(state) as c:r=c.execute('SELECT * FROM capability_configs WHERE role=?',(role,)).fetchone()
    if not r:raise CapabilityError('missing_capability','Configure '+role+' using capability-configure')
    if verified and r['status']!='available':raise CapabilityError('unverified_capability','Run capability-probe for '+role)
    return json.loads(r['config'])


def diagnose(state,required=None):
    if required is not None and (not isinstance(required,list) or any(r not in ROLES for r in required)):raise ValueError('invalid required roles')
    with connect(state) as c:
        rows={r['role']:r for r in c.execute('SELECT * FROM capability_configs')}
        roles={role:({'status':rows[role]['status'],'config':json.loads(rows[role]['config']),'revision':rows[role]['revision'],'verification':json.loads(rows[role]['verification']) if rows[role]['verification'] else None} if role in rows else {'status':'unconfigured'}) for role in ROLES}
    return {'roles':roles,'supported_adapters':ROLES,'missing':[r for r in required or [] if roles[r]['status']!='available'],'metadata_available':True,'next_actions':['capability-configure','capability-probe'],'host_native_vision_required':False}


def vision(state,verified=True):
    from .adapters.vision import Vision
    config=get_config(state,'vision',verified)
    if config['protocol']=='host':raise CapabilityError('host_action_required','Use image and evidence-submit with the host visual tool')
    return Vision(config)


def probe(state,role,result_id=None,file_id=None,text='a photograph',expected_text=None):
    config=get_config(state,role,False)
    revision=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    if config['protocol']=='host':
        raise CapabilityError('host_action_required','Host capabilities require real scoped image/evidence or vector submission; declaring a host model is not a probe')
    report={'checked_at':now(),'configuration_revision':revision,'quality':'not_evaluated','real_input_verified':False}
    try:
        from . import evidence
        import base64,tempfile
        from pathlib import Path
        if role!='description_text':
            if result_id is None or file_id is None:raise ValueError('probe requires an authorized result_id and file_id')
            pic=evidence.image(state,result_id,file_id)
            report['input_hash']=pic['hash']
        if role in ('image_text','description_text'):
            from .adapters.encoding import Encoder
            from .embeddings import unpack
            provider=Encoder(config);query=provider.encode(text)
            report.update({'dimensions':len(query)//4,'space':provider.space,'digest':provider.digest})
            if role=='image_text':
                image=provider.encode({'image':pic['data']})
                if len(image)!=len(query):raise CapabilityError('incompatible_space','Image/text dimensions differ')
                report['sample_similarity']=sum(a*b for a,b in zip(unpack(image),unpack(query)))
                if image==query:raise CapabilityError('invalid_response','Image/text encodings are identical; check real modality support')
                report['relevance']='requires labeled positive and negative quality assessment'
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'input.jpg';path.write_bytes(base64.b64decode(pic['data']))
                if role=='vision':
                    label,_=vision(state,False).label(path);report['sample']=label
                elif role=='ocr':
                    from .analysis_tools import ocr_image
                    output=ocr_image(state,path,config);report['sample']=output
                    if expected_text is None:raise ValueError('OCR probe needs expected_text to verify extraction')
                    if expected_text not in output['text']:raise CapabilityError('probe_failed','Expected text was not extracted')
                elif role=='faces':
                    from .people import detect
                    output=detect(config,path);report['detected_faces']=len(output)
                    if not output:raise CapabilityError('probe_failed','Use a known face image to validate face extraction')
        report['real_input_verified']=True;status='available'
    except CapabilityError as error:
        report['error']={'code':error.code,'message':str(error),'retryable':error.retryable};status='unreachable' if error.code=='unreachable' else 'verification_failed'
    with connect(state) as c:
        changed=c.execute('UPDATE capability_configs SET status=?,verification=?,updated=? WHERE role=? AND revision=?',(status,json.dumps(report,ensure_ascii=False),now(),role,revision)).rowcount
        if not changed:raise CapabilityError('version_conflict','Configuration changed during probe')
    return {'role':role,'status':status,'verification':report,'errors':[] if status=='available' else [report['error']]}
