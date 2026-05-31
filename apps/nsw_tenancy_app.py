from jurisdictions.nsw_tenancy import jurisdiction
from core.api import create_app

app = create_app(jurisdiction)
