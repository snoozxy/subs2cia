<<<<<<< Updated upstream
def main():
    from subs2cia.main import start
    start()

def subzipper_main():
    from subs2cia.subzipper import start
    start()
=======
from subs2cia.main import start as _start
from subs2cia.subzipper import start as _subzipper_start

def main():
    _start()

def subzipper_main():
    _subzipper_start()
>>>>>>> Stashed changes
