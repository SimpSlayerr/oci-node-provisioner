import os
import sys
import hashlib
import oci
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from oci.core import ComputeClient
from oci.identity import IdentityClient
from oci.core.models import (
    LaunchInstanceDetails,
    LaunchInstanceShapeConfigDetails,
    InstanceSourceViaImageDetails,
    CreateVnicDetails,
)

def get_fingerprint_from_pem(pem_str):
    """Calculates MD5 fingerprint directly from private key PEM."""
    try:
        key_obj = serialization.load_pem_private_key(
            pem_str.encode("utf-8"),
            password=None,
            backend=default_backend()
        )
        pub_der = key_obj.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        md5_digest = hashlib.md5(pub_der).hexdigest()
        return ":".join(md5_digest[i:i+2] for i in range(0, len(md5_digest), 2))
    except Exception as e:
        print(f"Error calculating fingerprint from key: {e}")
        return None

def main():
    user_id = os.environ.get("OCI_USER_ID", "").strip()
    secret_fingerprint = os.environ.get("OCI_FINGERPRINT", "").strip()
    tenancy_id = os.environ.get("OCI_TENANCY_ID", "").strip()
    region = os.environ.get("OCI_REGION", "eu-frankfurt-1").strip()
    raw_key = os.environ.get("OCI_KEY_CONTENT", "").strip()

    ssh_public_key = os.environ.get("OCI_SSH_PUBLIC_KEY", "").strip()
    subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip()
    image_id = os.environ.get("OCI_IMAGE_ID", "ocid1.image.oc1.eu-frankfurt-1.aaaaaaaaimlbvu2dnd46l4gmgpcykuuqm6v52u67tqki7hxmptppe4wdhwea").strip()

    # Normalize newlines (handles Windows \r\n and escaped \\n)
    if "\\n" in raw_key and "\n" not in raw_key:
        raw_key = raw_key.replace("\\n", "\n")
    private_key = "\n".join([line.strip() for line in raw_key.splitlines() if line.strip()])

    # Calculate true fingerprint from the private key
    calc_fingerprint = get_fingerprint_from_pem(private_key)
    fingerprint = calc_fingerprint if calc_fingerprint else secret_fingerprint

    print("=" * 50)
    print("OCI AUTHENTICATION DIAGNOSTICS")
    print(f"User OCID:          {user_id[:20]}...{user_id[-10:] if len(user_id) > 30 else ''}")
    print(f"Tenancy OCID:       {tenancy_id[:20]}...{tenancy_id[-10:] if len(tenancy_id) > 30 else ''}")
    print(f"Region:             {region}")
    print(f"Key Fingerprint:    {fingerprint}")
    if calc_fingerprint and secret_fingerprint and calc_fingerprint.lower() != secret_fingerprint.lower():
        print(f"⚠️  NOTICE: GitHub secret fingerprint ({secret_fingerprint}) differed from key; using calculated: {calc_fingerprint}")
    print("=" * 50)

    # Basic format check
    if not user_id.startswith("ocid1.user."):
        print("⚠️ WARNING: OCI_USER_ID does not start with 'ocid1.user.' — check if you pasted the wrong OCID.")
    if not tenancy_id.startswith("ocid1.tenancy."):
        print("⚠️ WARNING: OCI_TENANCY_ID does not start with 'ocid1.tenancy.' — check if you pasted the wrong OCID.")

    config = {
        "user": user_id,
        "fingerprint": fingerprint,
        "tenancy": tenancy_id,
        "region": region,
        "key_content": private_key,
    }

    try:
        oci.config.validate_config(config)
    except Exception as e:
        print(f"Config Validation Error: {e}")
        sys.exit(1)

    identity_client = IdentityClient(config)
    compute_client = ComputeClient(config)

    try:
        ads = identity_client.list_availability_domains(compartment_id=tenancy_id).data
        print(f"✅ Authentication SUCCESS! Found {len(ads)} Availability Domains in {region}.")
    except Exception as e:
        print(f"\n❌ AUTHENTICATION FAILED: {e}")
        print("\nFix checklist:")
        print(f"1. In Oracle Cloud Console -> My Profile -> API Keys, make sure fingerprint '{fingerprint}' exists.")
        print("2. If it does not exist, upload the public key matching this private key to Oracle.")
        sys.exit(1)

    fault_domains = ["FAULT-DOMAIN-1", "FAULT-DOMAIN-2", "FAULT-DOMAIN-3"]

    print(f"Scanning Availability Domains for ARM capacity (1 OCPU, 6GB RAM)...")

    for ad in ads:
        for fd in fault_domains:
            print(f"Testing {ad.name} | {fd}...")

            instance_details = LaunchInstanceDetails(
                compartment_id=tenancy_id,
                availability_domain=ad.name,
                fault_domain=fd,
                display_name="vless-proxy",
                shape="VM.Standard.A1.Flex",
                shape_config=LaunchInstanceShapeConfigDetails(
                    ocpus=1.0,
                    memory_in_gbs=6.0,
                ),
                source_details=InstanceSourceViaImageDetails(
                    image_id=image_id,
                ),
                create_vnic_details=CreateVnicDetails(
                    subnet_id=subnet_id,
                    assign_public_ip=True,
                ),
                metadata={
                    "ssh_authorized_keys": ssh_public_key,
                },
            )

            try:
                response = compute_client.launch_instance(instance_details)
                if response.data.lifecycle_state in ["PROVISIONING", "RUNNING"]:
                    print(f"🎉 SUCCESS! Instance provisioned in {ad.name} ({fd})!")
                    print(f"Instance ID: {response.data.id}")
                    sys.exit(0)
            except oci.exceptions.ServiceError as e:
                if "Out of host capacity" in str(e.message) or "TooManyRequests" in str(e.code) or e.status == 500:
                    print(f"   -> Out of capacity in {ad.name} ({fd})")
                else:
                    print(f"   -> OCI Error: {e.message}")
            except Exception as e:
                print(f"   -> Unexpected error: {e}")

    print("All domains full right now. Scheduled runner will retry in 10 minutes.")

if __name__ == "__main__":
    main()
