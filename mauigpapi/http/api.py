from .direct_inbox import DirectInboxAPI
from .login_simulate import LoginSimulateAPI
from .upload import UploadAPI


class AndroidAPI(DirectInboxAPI, LoginSimulateAPI, UploadAPI):
    pass
