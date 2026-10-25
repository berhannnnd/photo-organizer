"""Shared host-neutral tool boundary. No transport owns business logic."""
import platform
from .catalog import connect, report
from .lifecycle import synchronize as scan
from .results import create, page
from .planning import plan
from .execution import apply

from .operations import OPERATIONS as EXTENSIONS
from .errors import CapabilityError

API_VERSION = '2'
OPERATIONS = ('capabilities', 'status', 'scan', 'search', 'results', 'plan', 'apply', 'embed-index', 'describe-index', 'retrieve', 'review')


def dispatch(state, operation, arguments):
    if not isinstance(arguments, dict):
        return failure('invalid_request', 'arguments must be an object')
    try:
        if operation == 'capabilities':
            if arguments: raise ValueError('capabilities takes no arguments')
            data = {'api_version': API_VERSION, 'platform': platform.system(),
                    'operations': list(OPERATIONS)+list(EXTENSIONS), 'outputs': ['album', 'copy', 'compress'],
                    'query': ['metadata', 'indexed_facts', 'and', 'or', 'not', 'saved_semantic_judgments', 'image_text_candidates'],
                    'result_snapshots': True, 'models_required_for_metadata': False,
                    'vision_protocols': ['anthropic'],
                    'limitations': ['POSIX only; Windows unsupported', 'legacy direct calls are synchronous; use job-start for durable execution',
                                    'independent human quality and cross-host release acceptance pending']}
        elif operation in EXTENSIONS: data=EXTENSIONS[operation](state,**arguments)
        elif operation == 'status':
            if arguments: raise ValueError('status takes no arguments')
            with connect(state) as c: data = report(c)
        elif operation in ('embed-index','describe-index','retrieve'):
            from . import embeddings
            data = {'embed-index':embeddings.index,'describe-index':embeddings.index_descriptions,'retrieve':embeddings.search}[operation](state, **arguments)
        elif operation == 'review':
            from .provider import Provider
            from .semantic import enrich
            if set(arguments)-{'result_set_id','condition','config'} or not {'result_set_id','condition'}<=set(arguments): raise ValueError('review requires result_set_id and condition')
            if arguments.get('config'): provider=Provider.from_config(arguments['config'])
            else:
                from .capabilities import vision
                provider=vision(state)
            data=enrich(state,provider,arguments['condition'],workers=2,result_set_id=arguments['result_set_id'])
        elif operation == 'scan': data = scan(state, **arguments)
        elif operation == 'search': data = create(state, **arguments)
        elif operation == 'results': data = page(state, **arguments)
        elif operation == 'plan': data = plan(state, **arguments)
        elif operation == 'apply': data = apply(state, **arguments)
        else: return failure('unsupported_operation', 'unknown operation')
        status = 'partial_failed' if data.get('errors') or data.get('file_errors') else 'completed'
        return {'api_version': API_VERSION, 'status': status, 'data': data, 'error': None}
    except CapabilityError as error:
        return {'api_version':API_VERSION,'status':'failed','data':None,'error':{'code':error.code,'message':str(error),'retryable':error.retryable}}
    except PermissionError:
        return failure('permission_denied', 'filesystem permission denied')
    except FileNotFoundError:
        return failure('not_found', 'requested file or directory is unavailable')
    except (ValueError, TypeError) as error:
        return failure('invalid_request', str(error))
    except OSError:
        return failure('io_error', 'filesystem operation failed; inspect source availability and permissions')


def failure(code, message):
    return {'api_version': API_VERSION, 'status': 'failed', 'data': None,
            'error': {'code': code, 'message': message, 'retryable': False}}
