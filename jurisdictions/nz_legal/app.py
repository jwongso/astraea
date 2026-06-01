from core.api import create_app
from jurisdictions.nz_legal.jurisdiction import NZLegalJurisdiction

app = create_app(NZLegalJurisdiction())
