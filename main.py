import sys
import os

# Fix working directory when run as a frozen exe
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from ui import App

if __name__ == '__main__':
    app = App()
    app.mainloop()
