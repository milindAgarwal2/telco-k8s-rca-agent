# SCAS Search 3PP Integration Contract

This contract implements the SCAS Ordering Service API described in
`Software Composition Analysis Services REST APIs.pdf`, section 5.2.3.2.

## 1. Refresh-token exchange

```http
POST /registry/auth/token/refresh
Content-Type: application/x-www-form-urlencoded
Accept: application/json

refresh_token=<SCAS refresh token>
```

Production URL:

```text
https://scas.internal.ericsson.com/registry/auth/token/refresh
```

The response must contain:

```json
{
  "access_token": "<short-lived bearer token>",
  "expires_in": 900
}
```

`expires_in` is optional. When absent or invalid, the adapter caches the token
for a conservative ten minutes. A configured safety margin refreshes it before
expiry. An HTTP 401 from Search 3PP forces one refresh and one retry.

The refresh token is read from `SCAS_REFRESH_TOKEN` by default. It is never
written to configuration, reports, logs, MCP results or exception messages.

## 2. Search 3PP

Endpoint:

```http
GET /ordering/components/search
Authorization: Bearer <access_token>
Accept: application/json
```

Exact name-and-version attempt:

```text
?size=500
&filter=compName,likei,*Angular*
&filter=compVersion,NTXEQ,19.2.3
```

The actual URL encodes these characters. Multiple `filter` parameters remain
separate query parameters.

If the exact version attempt returns no matching records, the adapter performs
a name-only fallback for the same name:

```text
?size=500&filter=compName,likei,*Angular*
```

This distinguishes:

- exact component/version available;
- component available in other versions;
- component not found at all.

### Maven coordinate fallback

When both exact-version and name-only searches return no matching component for
a Maven coordinate, SCAS lookup uses this order:

| Stage | Input `com.itextpdf:io` | Name filter |
|---|---|---|
| 1 | full coordinate | `compName,likei,*com.itextpdf:io*` |
| 2 | text before `:` | `compName,likei,*com.itextpdf*` |
| 3 | exact group-leaf library | `compName,likei,itextpdf` |
| 4 | partial group-leaf library | `compName,likei,*itextpdf*` |

Each stage first includes `compVersion`; when empty, the optional name-only
query runs before proceeding to the next stage. The final library query has no
wildcard at stage 3; stage 4 deliberately restores wildcards for partial
matching. Partial results are tagged as review evidence and become Yellow.
This behavior is controlled by `maven_coordinate_fallback`, enabled by default.

## 3. Response mapping

SCAS commonly returns Spring-style pagination:

```json
{
  "content": [
    {
      "compName": "Angular",
      "compVersion": "19.2.3",
      "swType": "FOSS",
      "compProdNumber": "1/ABC123"
    }
  ],
  "totalElements": 1,
  "size": 500,
  "number": 0
}
```

Mappings:

| SCAS field | Agent field |
|---|---|
| `compName` | component name |
| `compVersion` | available version |
| explicit status/state, when present | catalog status |
| no explicit status | `available` |
| `compDownloadUrl` | details/download URL |
| Stako comment field | retained in raw catalog evidence for policy evaluation |

The parser also accepts arrays and collection keys `content`, `items`,
`results`, `components` and `data`.

## 4. Name matching

SCAS may append vendor information after a comma or `" - "`. The adapter first
compares the primary SCAS component name. Exact normalized matches can become
Green. Prefix/fuzzy matches are converted to review status and therefore
Yellow, preventing a similar component from being treated as an exact match.

## 5. Error semantics

| Condition | Result |
|---|---|
| Token environment variable absent | Grey with actionable configuration message |
| Refresh failure | Grey |
| Search timeout/TLS/network error | Grey |
| Search HTTP 401 | Refresh once and retry once |
| Invalid JSON | Grey |
| Successful empty exact search, other versions found | Amber |
| Successful empty name search | Red by default |
| Stako comment says “newer version exists” | Amber |
| Partial Maven name match | Yellow/manual confirmation |
| Approved Rosetta OCI whitelist match | Green without SCAS lookup |

The Stako override is evaluated before denied/unavailable status. Therefore
this specific comment never results in Yellow or Red.

## 6. Deferred repository sources

Direct searches against Ericsson's Maven repository and Ericsson's PyPI
Artifactory/JFrog are intentionally not implemented in this release. They will
be added as separate catalog adapters after endpoint, authentication, response
contract and governance precedence are approved.
