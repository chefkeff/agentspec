# Project Requirements for User Gateway

It is essential to make sure that all incoming requests must have an Authorization header present.
In order to handle authentication, the system should provide the ability to verify JWT tokens with public RSA keys.
It should be noted that we need to ensure that raw passwords are never logged under any circumstances.
Security constraint: PCI compliance is strictly required for billing endpoints.

## Tasks to be performed:
- [ ] Initialize the project repository with FastAPI and PostgreSQL
- [ ] Implement user authentication controller with bcrypt password hashing
- [ ] Connect Redis cache for user session persistence
- [ ] Build end-to-end integration test suite
