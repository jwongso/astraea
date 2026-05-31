from jurisdictions.nz_employment import jurisdiction
from core.api import create_app

app = create_app(jurisdiction)
