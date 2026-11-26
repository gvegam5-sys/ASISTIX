"""Single-use IPC worker for the synthetic integration harness."""
import sys
from comprobar_aislamiento import enter_job, is_appcontainer


def main():
    if not is_appcontainer():
        raise SystemExit('AppContainer required')
    job = enter_job()
    size = int.from_bytes(sys.stdin.buffer.read(4),'big')
    if not 0 < size <= 384*1024:
        raise SystemExit('Invalid capture length')
    image = sys.stdin.buffer.read(size)
    if not job or len(image) != size or sys.stdin.buffer.read(1):
        raise SystemExit('Invalid capture frame')
    from motor import CaptureError, FacialEngine
    try:
        result=FacialEngine().capture(image)
    except CaptureError as error:
        if sys.argv[1:]!=['--quality-feedback']:
            raise
        result=b'QUALITY:'+str(error).encode('ascii')
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()


if __name__=='__main__':
    main()
