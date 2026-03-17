# Runbook: Phase 2a — PostgreSQL & EF Core Wire-Up

**Phase:** 2 · Sub-phase a
**Estimated time:** ~1 hour
**Pause point:** `dotnet build` exits 0 and Migrations/ folder exists in the repo
**Machines:** DISCWORLD (PostgreSQL) · MIDDLEEARTH (API scaffold, migrations)

---

## Overview

Adds PostgreSQL 16 to the Docker Compose stack on DISCWORLD and builds the foundation of the .NET 8 Web API: a domain model, a DbContext, connection string configuration, and the first EF Core migration. The migration is not applied in this sub-phase — it runs automatically on startup via `db.Database.Migrate()`. Phase 2b adds the CRUD endpoints and Testcontainers CI tests.

**Connects to:** Phase 1b (Terraform + LocalStack running). Phase 2b follows immediately.

---

## Prerequisites

- Phase 1a complete: Docker running on DISCWORLD, `infra/docker/localstack.docker-compose.yml` exists
- MIDDLEEARTH WSL2 terminal open
- .NET 8 SDK installed on MIDDLEEARTH: `dotnet --version` → `8.0.x`
- EF Core CLI installed on MIDDLEEARTH: `dotnet ef --version`
  - If missing: `dotnet tool install --global dotnet-ef`
  - If `dotnet ef` not found after install: `export PATH="$PATH:$HOME/.dotnet/tools"` (add to `~/.bashrc`)
- psql client installed on MIDDLEEARTH for verification: `sudo apt install -y postgresql-client`

---

## Architecture Decision

**PostgreSQL 16 over SQL Server or MySQL** — PostgreSQL is the default relational database for cloud-native .NET projects. It runs identically locally and on RDS. The AWS equivalent (RDS PostgreSQL) requires zero code changes — only the connection string changes.

**EF Core migrations run on startup** — `db.Database.Migrate()` in `Program.cs` means the schema is always in sync with the code on every container start. No separate migration job is needed in CI or deployment pipelines.

**Connection string via `appsettings.Development.json`** — the committed `appsettings.json` has an empty placeholder. The real value is supplied by `appsettings.Development.json` (gitignored) locally, and by environment variable (`ConnectionStrings__DefaultConnection`) in CI and production. This pattern is identical for AWS — the value comes from Secrets Manager via an ECS task definition environment variable.

---

## Step 1 — Add PostgreSQL to the Docker Compose file

On **DISCWORLD**, edit `infra/docker/localstack.docker-compose.yml`:

```yaml
services:
  localstack:
    # ... unchanged

  postgres:
    image: postgres:16
    container_name: postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: apppassword
      POSTGRES_DB: cloudref
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser -d cloudref"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  localstack_data:
  postgres_data:
```

Start PostgreSQL on DISCWORLD:

```bash
cd infra/docker
docker compose -f localstack.docker-compose.yml --env-file .env up -d postgres
docker ps   # confirm postgres container is Up
```

Verify from **MIDDLEEARTH**:

```bash
psql "host=DISCWORLD port=5432 user=appuser password=apppassword dbname=cloudref" -c "\conninfo"
```

Expected: `You are connected to database "cloudref" as user "appuser"`.

If `DISCWORLD` doesn't resolve by hostname, use the IP address or add it to `/etc/hosts` on MIDDLEEARTH:
```bash
echo "192.168.x.x DISCWORLD" | sudo tee -a /etc/hosts
```

---

## Step 2 — Scaffold the .NET 8 Web API

On **MIDDLEEARTH**, from the repo root:

```bash
mkdir -p src/backend
cd src/backend
dotnet new webapi -n CloudRef.Api --framework net8.0
cd CloudRef.Api
```

Add required NuGet packages:

```bash
dotnet add package Npgsql.EntityFrameworkCore.PostgreSQL --version 8.0.11
dotnet add package Microsoft.EntityFrameworkCore.Design --version 8.0.11
dotnet add package Microsoft.AspNetCore.OpenApi
```

> **Note:** Specifying `--version 8.0.11` avoids NuGet resolving to a mismatched version. On a slow or cold NuGet cache each package add takes 20–60 seconds — this is normal.

---

## Step 3 — Create the domain model

Create `src/backend/CloudRef.Api/Domain/Product.cs`:

```csharp
namespace CloudRef.Api.Domain;

public class Product
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public decimal Price { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
```

---

## Step 4 — Create the DbContext

Create `src/backend/CloudRef.Api/Data/AppDbContext.cs`:

```csharp
using CloudRef.Api.Domain;
using Microsoft.EntityFrameworkCore;

namespace CloudRef.Api.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Product> Products => Set<Product>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Product>(entity =>
        {
            entity.HasKey(p => p.Id);
            entity.Property(p => p.Name).HasMaxLength(200).IsRequired();
            entity.Property(p => p.Description).HasMaxLength(1000);
            entity.Property(p => p.Price).HasPrecision(18, 2);
        });
    }
}
```

---

## Step 5 — Wire up Program.cs

Replace the contents of `src/backend/CloudRef.Api/Program.cs`:

```csharp
using CloudRef.Api.Data;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

var app = builder.Build();

// Apply migrations automatically on startup
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Database.Migrate();
}

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseAuthorization();
app.MapControllers();
app.Run();

// Required for Testcontainers WebApplicationFactory in Phase 2b
public partial class Program { }
```

---

## Step 6 — Add connection strings

Edit `src/backend/CloudRef.Api/appsettings.json` — add an empty placeholder (committed to repo):

```json
{
  "ConnectionStrings": {
    "DefaultConnection": ""
  },
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning"
    }
  },
  "AllowedHosts": "*"
}
```

Create `src/backend/CloudRef.Api/appsettings.Development.json` — **not committed** (already in `.gitignore`):

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Host=DISCWORLD;Port=5432;Database=cloudref;Username=appuser;Password=apppassword"
  }
}
```

> **Critical:** The hostname must be `DISCWORLD`, not `localhost`. The API runs on MIDDLEEARTH and connects to PostgreSQL on DISCWORLD over the LAN.

---

## Step 7 — Create and verify the first migration

From `src/backend/CloudRef.Api/`:

```bash
dotnet ef migrations add InitialCreate
```

Expected output ending with: `Done. To undo this action, use 'ef migrations remove'`

This creates `Migrations/` with three files. The migration is not applied here — `db.Database.Migrate()` in `Program.cs` applies it on first startup.

Verify the build compiles cleanly:

```bash
dotnet build
```

Expected: `Build succeeded.` with 0 errors.

**Pause point reached** when `dotnet build` exits 0 and `Migrations/` exists.

---

## Step 8 — Commit

From the repo root on MIDDLEEARTH:

```bash
git add infra/docker/localstack.docker-compose.yml \
        src/backend/CloudRef.Api/ \
        .env.example
git commit -m "feat(backend): .NET 8 API scaffold, EF Core, PostgreSQL, InitialCreate migration"
git push
```

Confirm the CI `scaffold-check` job stays green. No new CI job yet — that's Phase 2b.

---

## How to Verify

| Check | Command | Expected |
|---|---|---|
| PostgreSQL running | `docker ps` on DISCWORLD | `postgres` container Up |
| Connection from MIDDLEEARTH | `psql "host=DISCWORLD ..."` | Connected |
| Build clean | `dotnet build` from `src/backend/CloudRef.Api/` | 0 errors |
| Migrations generated | `ls src/backend/CloudRef.Api/Migrations/` | `InitialCreate` files present |
| API starts locally | `dotnet run` from `src/backend/CloudRef.Api/` | Migrations apply, Swagger at `http://localhost:5000/swagger` |

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `psql: could not connect to server` | Port 5432 blocked on DISCWORLD | `sudo ufw allow 5432` on DISCWORLD |
| `No connection string named 'DefaultConnection'` | `appsettings.Development.json` not present | Create it with the DISCWORLD connection string — do not commit it |
| `dotnet ef: command not found` | EF CLI not on PATH | `export PATH="$PATH:$HOME/.dotnet/tools"` then retry |
| NuGet `dotnet add package` hangs for 60+ seconds | Cold NuGet cache on first run | Wait — first run takes up to 3 minutes; subsequent runs use cache |
| `Host=localhost` in connection string | Wrote wrong hostname | Must be `DISCWORLD` — the API is on MIDDLEEARTH, PostgreSQL is on DISCWORLD |
| `role "appuser" does not exist` | Container started before env vars applied | `docker compose down -v && docker compose up -d postgres` on DISCWORLD |
| `Unable to create an object of type 'AppDbContext'` during `dotnet ef migrations add` | Missing design-time factory or connection string | Ensure `appsettings.Development.json` exists with a valid connection string |

---

## AWS Equivalent

- PostgreSQL → RDS PostgreSQL (`db.t3.micro` for dev, `db.t3.small`+ for staging)
- Connection string injected via AWS Secrets Manager → ECS task definition environment variable
- `db.Database.Migrate()` runs automatically on every container start — no separate migration job needed
- `AWSSDK_ENDPOINT_URL` is unrelated to PostgreSQL; RDS is always a real AWS endpoint

---

## Further Reading

- [EF Core migrations](https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/)
- [Npgsql EF Core provider](https://www.npgsql.org/efcore/)
- [DbContext configuration](https://learn.microsoft.com/en-us/ef/core/dbcontext-configuration/)
