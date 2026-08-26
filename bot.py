import os
import sys
import oci
from oci.core import ComputeClient
from oci.identity import IdentityClient
from oci.core.models import (
    LaunchInstanceDetails,
    LaunchInstanceShapeConfigDetails,
    InstanceSourceViaImageDetails,
    CreateVnicDetails,
)

def main():
    user_id = os.environ.get("OCI_USER_ID", "").strip()
    fingerprint = os.environ.get("OCI_FINGERPRINT", "").strip()
    tenancy_id = os.environ.get("OCI_TENANCY_ID", "").strip()
    region = os.environ.get("OCI_REGION", "eu-frankfurt-1").strip()
    private_key = os.environ.get("OCI_KEY_CONTENT", "").strip()

    ssh_public_key = os.environ.get("OCI_SSH_PUBLIC_KEY", "").strip()
    subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip()
    image_id = os.environ.get("OCI_IMAGE_ID", "ocid1.image.oc1.eu-frankfurt-1.aaaaaaaaimlbvu2dnd46l4gmgpcykuuqm6v52u67tqki7hxmptppe4wdhwea").strip()

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
    except Exception as e:
        print(f"Error fetching Availability Domains: {e}")
        sys.exit(1)

    fault_domains = ["FAULT-DOMAIN-1", "FAULT-DOMAIN-2", "FAULT-DOMAIN-3"]

    print(f"Scanning {len(ads)} Availability Domains in {region} for ARM capacity (1 OCPU, 6GB RAM)...")

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
