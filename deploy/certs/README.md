# TLS certificates

Put the certificate files for the HTTPS proxy here (they are git-ignored):

- `fullchain.pem`: the certificate followed by the intermediate certificates
- `privkey.pem`: the private key

Use the certificate issued by your organization's IT department. For a test setup, see
"HTTPS Reverse Proxy" in [docs/docker_deployment.md](../../docs/docker_deployment.md) for a self-signed certificate.
