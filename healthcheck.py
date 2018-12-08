import os
import sys

import requests
from requests import RequestException


def main(timeout=10):
    port = os.getenv('PORT', 8000)
    try:
        res = requests.get(f'http://127.0.0.1:{port}/api/ping', timeout=timeout)
        res.raise_for_status()

        if res.json().get('status') != 'alive':
            sys.exit(1)

    except RequestException:  # Covers at least timeout and status >= 400
        sys.exit(1)


if __name__ == '__main__':
    main()
