from .thread import ThreadAPI
from .login_simulate import LoginSimulateAPI
from .upload import UploadAPI


class AndroidAPI(ThreadAPI, LoginSimulateAPI, UploadAPI):
    pass
