"""Bounded JSON HTTP transport with classified errors and safe credential references."""
import json
import os
import urllib.error
import urllib.request
from ..errors import CapabilityError

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise CapabilityError('redirect_refused','Configure the final service endpoint; credential redirects are refused')


def request(config,body,path='',headers=None):
    credential=config.get('api_key_env')
    key=os.environ.get(credential) if credential else None
    if credential and not key:raise CapabilityError('authentication_required','Configured credential environment variable is missing')
    h={'Content-Type':'application/json',**(headers or {})}
    if key:h['Authorization']='Bearer '+key
    if config['protocol']=='anthropic' and key:h.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
    req=urllib.request.Request(config['endpoint'].rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=config.get('timeout',90)) as response:
            data=response.read(8_000_001)
            if len(data)>8_000_000:raise CapabilityError('invalid_response','Model response exceeds byte budget')
            return json.loads(data)
    except urllib.error.HTTPError as e:
        status=e.code;e.close()
        code={401:'authentication_failed',403:'permission_denied',404:'model_or_endpoint_missing',429:'rate_limited',400:'unsupported_input'}.get(status,'provider_failed')
        raise CapabilityError(code,'Provider HTTP '+str(status),status==429 or status>=500) from None
    except (urllib.error.URLError,TimeoutError):
        raise CapabilityError('unreachable','Provider unavailable or timed out; billing outcome may be unknown',True) from None
    except (json.JSONDecodeError,UnicodeError):
        raise CapabilityError('invalid_response','Provider did not return valid JSON') from None
