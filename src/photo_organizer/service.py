"""Shared host-neutral tool boundary. No transport owns business logic."""
import platform
from .catalog import connect, report
from .ingest import scan
from .results import create, page
from .planning import plan
from .execution import apply

API_VERSION = '1'
OPERATIONS = ('capabilities', 'status', 'scan', 'search', 'results', 'plan', 'apply')


def dispatch(state, operation, arguments):
    if not isinstance(arguments, dict):
        return failure('invalid_request', 'arguments must be an object')
    try:
        if operation == 'capabilities':
            if arguments: raise ValueError('capabilities takes no arguments')
            data = {'api_version': API_VERSION, 'platform': platform.system(),
                    'operations': list(OPERATIONS), 'outputs': ['album', 'copy', 'compress'],
                    'query': ['metadata', 'indexed_facts', 'and', 'or', 'not', 'saved_semantic_judgments'],
                    'result_snapshots': True, 'models_required_for_metadata': False,
                    'vision_protocols': ['anthropic'],
                    'limitations': ['POSIX only; Windows unsupported', 'synchronous tasks; persistent job scheduler pending',
                                    'unknown and unanalyzed counts currently combined', 'single grouping level plus month hierarchy',
                                    'embedding, face clustering, watcher and automatic grouping pending']}
        elif operation == 'status':
            if arguments: raise ValueError('status takes no arguments')
            with connect(state) as c: data = report(c)
        elif operation == 'scan': data = scan(state, **arguments)
        elif operation == 'search': data = create(state, **arguments)
        elif operation == 'results': data = page(state, **arguments)
        elif operation == 'plan': data = plan(state, **arguments)
        elif operation == 'apply': data = apply(state, **arguments)
        else: return failure('unsupported_operation', 'unknown operation')
        status = 'partial_failed' if data.get('errors') or data.get('file_errors') else 'completed'
        return {'api_version': API_VERSION, 'status': status, 'data': data, 'error': None}
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
