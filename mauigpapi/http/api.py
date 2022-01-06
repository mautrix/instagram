from .account import AccountAPI
from .challenge import ChallengeAPI
from .login import LoginAPI
from .qe import QeSyncAPI
from .thread import ThreadAPI
from .upload import UploadAPI
from .user import UserAPI


class AndroidAPI(ThreadAPI, AccountAPI, QeSyncAPI, LoginAPI, UploadAPI, ChallengeAPI, UserAPI):
    pass
