import sys, importlib
print('Python:', sys.executable)
mods = ['streamlit','pandas','dateutil','plotly.express','requests','wikipedia','fuzzywuzzy']
for m in mods:
    try:
        importlib.import_module(m)
        print('OK:', m)
    except Exception as e:
        print('FAIL:', m, '->', e)
