from .thread import ThreadAPI
from .login_simulate import LoginSimulateAPI
from .upload import UploadAPI
from .challenge import ChallengeAPI


class AndroidAPI(ThreadAPI, LoginSimulateAPI, UploadAPI, ChallengeAPI):
    pass
