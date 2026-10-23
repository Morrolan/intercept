#!/usr/bin/env python3
"""Generate an AMI bearer secret and its one-way Intercept configuration digest."""
import hashlib
import secrets

if __name__ == "__main__":
    token = secrets.token_urlsafe(48)
    print("AMI service token (save securely; paste into AMI Modules):")
    print(token)
    print("\nIntercept private environment setting:")
    print("INTERCEPT_AMI_TOKEN_SHA256=" + hashlib.sha256(token.encode()).hexdigest())
