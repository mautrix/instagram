from .account import AccountAPI
from .challenge import ChallengeAPI
from .login import LoginAPI
from .thread import ThreadAPI
from .upload import UploadAPI
from .user import UserAPI


class AndroidAPI(ThreadAPI, AccountAPI, LoginAPI, UploadAPI, ChallengeAPI, UserAPI):
    pass
