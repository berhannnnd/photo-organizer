"""Operation registration only; implementations live in focused domain modules."""
from . import selection,evidence,organization

OPERATIONS = {
    'select':selection.choose,'combine':selection.combine,
    'evidence-submit':evidence.submit,'evidence-read':evidence.read,'image':evidence.image,
    'group-propose':organization.propose,'group-read':organization.group_detail,
    'plan-read':organization.plan_detail,'collection':organization.collection,
}
