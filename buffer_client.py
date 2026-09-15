"""Buffer's current GraphQL API. Owner credential stays on the server.

Do not retry createPost automatically: an HTTP failure may follow a successful
external write. The caller must retain an uncertain attempt for reconciliation.
Reference: https://developers.buffer.com/reference.html (2026-09-15).
"""
import os

import httpx


class BufferError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class BufferClient:
    def __init__(self, client):
        self.client = client

    async def query(self, query, variables=None, *, writing=False, allow_partial=False):
        key = os.environ.get("BUFFER_API_KEY", "").strip()
        if not key:
            raise BufferError("Add BUFFER_API_KEY to the server settings first.")
        try:
            r = await self.client.post(
                "https://api.buffer.com", headers={"Authorization": f"Bearer {key}"},
                json={"query": query, "variables": variables or {}}, timeout=35,
            )
        except httpx.HTTPError:
            raise BufferError("Buffer did not confirm the request. Check its dashboard before any retry.", writing) from None
        if r.status_code >= 400:
            safe = {401: "Buffer key was rejected. Reconnect with a valid key.",
                    403: "Buffer denied access to this account.",
                    429: "Buffer rate limit reached. Try again later."}
            raise BufferError(safe.get(r.status_code, "Buffer is temporarily unavailable."),
                              writing and r.status_code not in (401, 403, 429))
        try:
            body = r.json()
            if (body.get("errors") and not allow_partial) or not isinstance(body.get("data"), dict):
                raise ValueError()
        except (ValueError, AttributeError):
            # Do not echo provider payloads: they may contain customer content.
            raise BufferError("Buffer could not confirm the operation. Review the connection and API permissions.", writing) from None
        return body["data"]

    async def account(self):
        return (await self.query("query { account { id organizations { id name } } }"))["account"]

    async def channels(self, organization_id):
        return (await self.query("""query($input: ChannelsInput!) {
          channels(input: $input) { id name displayName service organizationId
            isDisconnected isLocked isQueuePaused }
        }""", {"input": {"organizationId": organization_id}}))["channels"]

    async def create(self, payload):
        result = (await self.query("""mutation($input: CreatePostInput!) {
          createPost(input: $input) {
            __typename
            ... on PostActionSuccess { post { id status externalLink channelId text } }
            ... on MutationError { message }
          }
        }""", {"input": payload}, writing=True)).get("createPost") or {}
        if result.get("__typename") != "PostActionSuccess":
            raise BufferError("Buffer rejected the post. Check the media format, caption, channel permissions and plan limits.",
                              result.get("__typename") not in ("InvalidInputError", "LimitReachedError", "UnauthorizedError", "NotFoundError"))
        if not (result.get("post") or {}).get("id"):
            raise BufferError("Buffer accepted the request without a post ID. Reconcile before retrying.", True)
        return result["post"]

    async def post(self, post_id):
        return (await self.query("""query($input: PostInput!) {
          post(input: $input) { id status externalLink channelId text }
        }""", {"input": {"id": post_id}}))["post"]

    async def posts(self, ids):
        # Batch status checks to conserve the account's daily API allowance.
        variables = {f"i{i}": {"id": pid} for i, pid in enumerate(ids)}
        decl = ",".join(f"$i{i}: PostInput!" for i in range(len(ids)))
        fields = " ".join(f"p{i}: post(input: $i{i}) {{ id status externalLink channelId text }}" for i in range(len(ids)))
        return await self.query(f"query({decl}) {{ {fields} }}", variables, allow_partial=True)
