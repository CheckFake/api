import os
import sys

import requests


def main():
    port = os.getenv('PORT', 8000)
    res = requests.get(f'http://127.0.0.1:{port}/api/ping')
    if res.status_code >= 400:
        sys.exit(1)

    if res.json().get('status') != 'alive':
        sys.exit(1)


if __name__ == '__main__':
    main()
