from .thread import ThreadAPI
from .upload import UploadAPI
from .challenge import ChallengeAPI
from .account import AccountAPI
from .qe import QeSyncAPI
from .login import LoginAPI


class AndroidAPI(ThreadAPI, AccountAPI, QeSyncAPI, LoginAPI, UploadAPI, ChallengeAPI):
    pass
