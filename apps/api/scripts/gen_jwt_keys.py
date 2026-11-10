"""Genera el par de claves Ed25519 para firmar los JWT de acceso.

Uso: python scripts/gen_jwt_keys.py  -> imprime la privada (para el Secret de k3s) y la pública.
Nunca subas la clave privada al repositorio.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
print(private_pem)
print(public_pem)
