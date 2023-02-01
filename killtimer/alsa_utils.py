from ctypes import *
from contextlib import contextmanager
import pyaudio

ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)


def py_error_handler(filename, line, function, err, fmt):
    pass


c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)


@contextmanager
def noalsaerr():
    lib = cdll.LoadLibrary('libasound.so')
    lib.snd_lib_error_set_handler(c_error_handler)
    yield
    lib.snd_lib_error_set_handler(None)
