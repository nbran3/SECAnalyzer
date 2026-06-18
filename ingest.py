import os
from dotenv import load_dotenv
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient
from pathlib import Path


load_dotenv()
container_name = os.getenv("AzureBlobContainerName")
account_url = os.getenv("AzureAccountUrl")
tenate_id = os.getenv("AzureTenantId")
client_id = os.getenv("AzureClientId")
client_secret = os.getenv("AzureClientSecret")
credential = ClientSecretCredential(
        tenant_id=tenate_id,
        client_id=client_id,
        client_secret=client_secret
    )

companies = [
    "Apple Inc.",
    "Microsoft Corp",
    "Amazon.com Inc",
    "Alphabet Inc. (Google)",
    "Meta Platforms Inc",
    "Tesla Inc",
    "NVIDIA Corp",
    "Walmart Inc",
    "JPMorgan Chase & Co",
    "Walt Disney Co",
    "Coca-Cola Co",
]

dir_path = Path("./")

blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
container_client = blob_service_client.get_container_client(container_name)

for file_path in dir_path.glob("*.txt"):
    blob_name = file_path.name 
    blob_client = container_client.get_blob_client(blob_name)
    print(f"Uploading {file_path} to Azure Blob Storage...")
    with open(file_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True)
    print(f"Finished uploading {file_path}.")
    os.remove(file_path)
    print(f"Deleted local file {file_path}.")
