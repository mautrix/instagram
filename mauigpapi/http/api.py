from .direct_inbox_feed import DirectInboxAPI
from .login_simulate import LoginSimulateAPI


class AndroidAPI(DirectInboxAPI, LoginSimulateAPI):
    pass
