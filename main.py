import argparse,ctypes,sys,logging
from clear_mic.paths import initialize
def main():
    ctypes.windll.kernel32.SetErrorMode(3)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    initialize();parser=argparse.ArgumentParser();parser.add_argument('--tray',action='store_true');parser.add_argument('--ui-test',action='store_true');parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    from clear_mic.paths import DATA
    logging.basicConfig(filename=DATA/'logs'/'app.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.self_test:
        from clear_mic.self_test import run
        run();return
    if not args.ui_test:
        from clear_mic.instance import acquire
        if not acquire():return
    import tkinter as tk
    from clear_mic.gui import App
    root=tk.Tk();app=App(root)
    if args.ui_test and app.tray is None:raise RuntimeError('System tray initialization failed')
    if args.tray and app.tray:root.withdraw()
    if args.ui_test:root.after(1200,app.quit)
    root.mainloop()
if __name__=='__main__':
    try:main()
    except Exception:
        logging.exception('Clear Mic failed')
        if '--self-test' not in sys.argv and '--ui-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,'Clear Mic could not start. See the app data folder logs for details.','Clear Mic',0x10)
        raise SystemExit(1)
