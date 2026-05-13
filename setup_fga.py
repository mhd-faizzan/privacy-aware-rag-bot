import os
import asyncio
import logging

from dotenv import load_dotenv
from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from openfga_sdk.credentials import CredentialConfiguration, Credentials

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def setup_authorization():
    """
    Creates the FGA authorization model and writes permission tuples.
    Run this once before starting the app.
    """
    config = ClientConfiguration(
        api_url=os.getenv("FGA_API_URL"),
        store_id=os.getenv("FGA_STORE_ID"),
        credentials=Credentials(
            method="client_credentials",
            configuration=CredentialConfiguration(
                api_token_issuer=os.getenv("FGA_TOKEN_ISSUER"),
                api_audience=os.getenv("FGA_API_AUDIENCE"),
                client_id=os.getenv("FGA_CLIENT_ID"),
                client_secret=os.getenv("FGA_CLIENT_SECRET"),
            ),
        ),
    )

    async with OpenFgaClient(config) as fga_client:
        # define the authorization model
        model = {
            "schema_version": "1.1",
            "type_definitions": [
                {
                    "type": "user",
                    "relations": {}
                },
                {
                    "type": "document",
                    "relations": {
                        "viewer": {
                            "this": {}
                        }
                    },
                    "metadata": {
                        "relations": {
                            "viewer": {
                                "directly_related_user_types": [
                                    {"type": "user"}
                                ]
                            }
                        }
                    }
                }
            ]
        }

        logger.info("Writing authorization model...")
        await fga_client.write_authorization_model(model)
        logger.info("Authorization model created")

        # nova is manager — can see everything
        # rex is employee — can only see general handbook
        tuples = [
            ClientTuple(user="user:nova", relation="viewer", object="document:salary_policy"),
            ClientTuple(user="user:nova", relation="viewer", object="document:budget_q4"),
            ClientTuple(user="user:nova", relation="viewer", object="document:general_handbook"),
            ClientTuple(user="user:rex", relation="viewer", object="document:general_handbook"),
        ]

        logger.info("Writing permission tuples...")
        await fga_client.write(ClientWriteRequest(writes=tuples))
        logger.info("Permissions set successfully")
        logger.info("nova can access: salary_policy, budget_q4, general_handbook")
        logger.info("rex can access: general_handbook only")


if __name__ == "__main__":
    asyncio.run(setup_authorization())