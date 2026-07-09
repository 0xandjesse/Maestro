"""Maestro Zero Trust Crypto Primitives — Ed25519 via PyNaCl."""
import hashlib
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey


def hash_string(input_str: str) -> str:
    """SHA-256 hash of a UTF-8 string. Returns lowercase hex."""
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()


def hash_concat(*parts: str) -> str:
    """SHA-256 of concatenated parts."""
    return hash_string("".join(parts))


def generate_key_pair() -> dict:
    """Generate a new Ed25519 key pair."""
    sk = SigningKey.generate()
    return {
        "private_key": sk.encode(encoder=HexEncoder).decode(),
        "public_key": sk.verify_key.encode(encoder=HexEncoder).decode(),
    }


def sign(message: str, private_key_hex: str) -> str:
    """Sign the SHA-256 hash of message with the given private key. Returns lowercase hex signature."""
    msg_hash = hashlib.sha256(message.encode("utf-8")).digest()
    sk = SigningKey(bytes.fromhex(private_key_hex))
    signed = sk.sign(msg_hash)
    return signed.signature.hex()


def verify(message: str, signature_hex: str, public_key_hex: str) -> bool:
    """Verify the signature of the SHA-256 hash of message against the public key."""
    msg_hash = hashlib.sha256(message.encode("utf-8")).digest()
    try:
        vk = VerifyKey(bytes.fromhex(public_key_hex))
        vk.verify(msg_hash, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False


def original_signature_payload(content: str, timestamp: int, sender_agent_id: str) -> str:
    """Build the canonical payload for the original message signature."""
    return hash_concat(content, str(timestamp), sender_agent_id)


def attestation_payload(previous_signature: str, content_hash: str, timestamp: int) -> str:
    """Build the canonical payload for an attestation."""
    return hash_concat(previous_signature, content_hash, str(timestamp))
