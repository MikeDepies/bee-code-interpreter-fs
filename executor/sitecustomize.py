import sys
import json
from datetime import datetime, date
from functools import wraps
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return {"__type__": obj.__class__.__name__, "value": obj.isoformat()}
        return super().default(obj)

def datetime_decoder(dct):
    if "__type__" in dct:
        type_name = dct["__type__"]
        if type_name == "datetime":
            return datetime.fromisoformat(dct["value"])
        elif type_name == "date":
            return date.fromisoformat(dct["value"])
    return dct

original_import = __import__

def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = original_import(name, globals, locals, fromlist, level)

    if name == "matplotlib.pyplot":
        sys.modules["matplotlib.pyplot"].show = lambda: sys.modules[
            "matplotlib.pyplot"
        ].savefig("plot.png")
    elif name == "moviepy.editor":
        original_write_videofile = sys.modules[
            "moviepy.editor"
        ].VideoClip.write_videofile
        sys.modules["moviepy.editor"].VideoClip.write_videofile = (
            lambda self, *args, **kwargs: original_write_videofile(
                self, *args, verbose=False, logger=None, **kwargs
            )
        )
    elif name == "PIL":
        original_import("PIL.ImageShow", globals, locals, fromlist, level)
        sys.modules["PIL.ImageShow"].show = lambda img, *args, **kwargs: img.save(
            "image.png"
        )
    elif name == "json":
            # Patch json module to use our custom encoder by default
            module.JSONEncoder = DateTimeEncoder
            module._default_encoder = DateTimeEncoder(
                skipkeys=False,
                ensure_ascii=True,
                check_circular=True,
                allow_nan=True,
                indent=None,
                separators=None,
                default=None,
            )
            # Add loads with custom decoder
            original_loads = module.loads
            @wraps(original_loads)
            def patched_loads(*args, **kwargs):
                if 'object_hook' not in kwargs:
                    kwargs['object_hook'] = datetime_decoder
                return original_loads(*args, **kwargs)
            module.loads = patched_loads

    return module

__builtins__["__import__"] = patched_import
