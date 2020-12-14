from .thread import ThreadAPI
from .upload import UploadAPI
from .challenge import ChallengeAPI
from .account import AccountAPI
from .qe import QeSyncAPI
from .login import LoginAPI
from .user import UserAPI


class AndroidAPI(ThreadAPI, AccountAPI, QeSyncAPI, LoginAPI, UploadAPI, ChallengeAPI, UserAPI):
    pass
