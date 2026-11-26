"""Opaque, single-connection TLS relay for the loopback experiment."""
import socket
import threading


def relay(client, ciphertext_input, ciphertext_output, observer):
    def client_to_gateway():
        try:
            while True:
                data=client.recv(65536)
                if not data:
                    return
                observer(data)
                ciphertext_input.write(data)
                ciphertext_input.flush()
        except (ConnectionError, TimeoutError):
            pass
        finally:
            ciphertext_input.close()

    reader=threading.Thread(target=client_to_gateway,daemon=True)
    reader.start()
    try:
        while True:
            data=ciphertext_output.read1(65536)
            if not data:
                return
            observer(data)
            client.sendall(data)
    except (ConnectionError, TimeoutError):
        pass
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        reader.join(timeout=4)
        client.close()
