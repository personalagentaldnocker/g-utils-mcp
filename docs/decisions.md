# Implementation decisions

- One Cloud Run service contains stateless Streamable HTTP MCP, Google enrollment
  callbacks, and artifact transfer. GCS holds durable state; no sticky sessions.
- Use official MCP SDK 1.30.0 from the committed uv lock. The upstream main README
  showed v2 APIs, but the released 1.x SDK installed here provides the tested
  low-level Server/StreamableHTTPSessionManager APIs. Upgrade via deliberate testing.
- Explicit method registry plus pinned official Discovery schemas. Generation
  supplies validation/catalog metadata, never automatic permission grants.
- Static principal bearer credentials are the initial Claude Code mode. Real cloud
  session support is an unrun acceptance gate; no speculative identity-provider
  dependency or homemade OAuth authorization server was added.
- Google OAuth is administratively initiated and bound to expected account/client/
  scopes/secret. Callback writes the approved token secret, not the policy. Operator
  activation is an explicit local policy edit and generation-guarded publication.
- Dedicated Drive account uses account-wide resource access. Principal method and
  account grants still apply. Docs uses that same Drive binding. Folder-restriction
  machinery and Sheets/Slides content APIs are outside this release.
- Foundation/service Terraform roots solve initial image and service-URL bootstrap.
  Local Docker builds avoid introducing a Cloud Build identity. State bootstrap is
  optional and separate from policy/temp storage.
- Binary transfers are bounded at 20 MB and remain authenticated; no public signed
  download URLs. Artifacts and page handles retain caller/context/source binding.
