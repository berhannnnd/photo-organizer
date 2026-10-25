"""Operation registration only; implementations live in focused domain modules."""
from . import selection,evidence,organization,capabilities,analysis_tools,people,discovery,jobs,lifecycle

OPERATIONS = {
    'roots':lifecycle.roots,'sync':lifecycle.synchronize,'watch':lifecycle.watch,'cache-cleanup':lifecycle.cleanup,
    'job-start':jobs.start,'job-status':jobs.status,'job-control':jobs.control,'job-recover':jobs.recover,
    'capability-configure':capabilities.configure,'capability-status':capabilities.diagnose,'capability-probe':capabilities.probe,
    'analyze':analysis_tools.analyze,'analysis-submit':analysis_tools.submit,'text-search':analysis_tools.text_search,'rank':analysis_tools.rank,
    'face-submit':people.submit,'people-cluster':people.cluster,'people':people.manage,'group-suggest':discovery.suggest,
    'select':selection.choose,'combine':selection.combine,
    'evidence-submit':evidence.submit,'evidence-read':evidence.read,'image':evidence.image,
    'group-propose':organization.propose,'group-read':organization.group_detail,
    'plan-read':organization.plan_detail,'collection':organization.collection,
}
