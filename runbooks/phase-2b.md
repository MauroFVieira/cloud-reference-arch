# Runbook: Phase 2b — CRUD Endpoints + Testcontainers Integration Tests

**Phase:** 2 · Sub-phase b
**Estimated time:** ~1.5 hours
**Pause point:** All integration tests green in CI on the self-hosted runner
**Machines:** DISCWORLD (CI execution) · MIDDLEEARTH (development)

---

## Overview

Implements the full CRUD REST API for the `Product` entity and adds a Testcontainers-based integration test suite. Each test run spins up a real PostgreSQL 16 container, applies migrations, runs all tests, then destroys the container — no mocks, no shared state. This is the first CI run that exercises actual application logic end-to-end.

**Connects to:** Phase 2a (API scaffold, EF Core, migration in place). Phase 3 (MongoDB) follows.

---

## Prerequisites

- Phase 2a complete: `dotnet build` exits 0, `Migrations/` folder exists
- PostgreSQL running on DISCWORLD: `docker ps` shows `postgres` container Up
- .NET 8 SDK on MIDDLEEARTH: `dotnet --version` → `8.0.x`
- Self-hosted runner on DISCWORLD showing `Idle` in GitHub Actions settings

---

## Architecture Decision

**Testcontainers over mocking the DbContext** — mocked EF Core tests pass reliably in isolation but miss a large class of real failures: migration errors, constraint violations, connection pooling issues, query translation bugs. Testcontainers spins up a real database container per test run, eliminating the gap between local and production behaviour. Tests that pass here are guaranteed to behave the same way against RDS.

**`WebApplicationFactory<Program>` as the test host** — this boots the real ASP.NET Core pipeline with a swapped-out DbContext. Middleware, routing, model binding, and serialization are all exercised. These are true integration tests, not unit tests of the controller in isolation.

**Idempotency test** — `db.Database.Migrate()` is called on every app startup. Verifying it doesn't throw on an already-migrated database prevents a class of deployment failures that only surface when a container restarts after the schema is already current.

---

## Step 1 — Add the Products controller

Create `src/backend/CloudRef.Api/Controllers/ProductsController.cs`:

```csharp
using CloudRef.Api.Data;
using CloudRef.Api.Domain;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace CloudRef.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ProductsController(AppDbContext db) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<IEnumerable<Product>>> GetAll() =>
        await db.Products.OrderBy(p => p.Id).ToListAsync();

    [HttpGet("{id:int}")]
    public async Task<ActionResult<Product>> GetById(int id)
    {
        var product = await db.Products.FindAsync(id);
        return product is null ? NotFound() : Ok(product);
    }

    [HttpPost]
    public async Task<ActionResult<Product>> Create(Product product)
    {
        product.CreatedAt = DateTime.UtcNow;
        db.Products.Add(product);
        await db.SaveChangesAsync();
        return CreatedAtAction(nameof(GetById), new { id = product.Id }, product);
    }

    [HttpPut("{id:int}")]
    public async Task<IActionResult> Update(int id, Product product)
    {
        if (id != product.Id) return BadRequest();
        db.Entry(product).State = EntityState.Modified;
        await db.SaveChangesAsync();
        return NoContent();
    }

    [HttpDelete("{id:int}")]
    public async Task<IActionResult> Delete(int id)
    {
        var product = await db.Products.FindAsync(id);
        if (product is null) return NotFound();
        db.Products.Remove(product);
        await db.SaveChangesAsync();
        return NoContent();
    }
}
```

Verify the API still builds:

```bash
dotnet build src/backend/CloudRef.Api/CloudRef.Api.csproj
```

---

## Step 2 — Scaffold the integration test project

From the repo root on **MIDDLEEARTH**:

```bash
dotnet new xunit -n CloudRef.Integration.Tests \
  --output tests/integration/CloudRef.Integration.Tests

cd tests/integration/CloudRef.Integration.Tests

dotnet add package Testcontainers.PostgreSql
dotnet add package Microsoft.AspNetCore.Mvc.Testing

dotnet add reference ../../../src/backend/CloudRef.Api/CloudRef.Api.csproj
```

---

## Step 3 — Create a solution file

From the repo root:

```bash
dotnet new sln -n CloudRef
dotnet sln add src/backend/CloudRef.Api/CloudRef.Api.csproj
dotnet sln add tests/integration/CloudRef.Integration.Tests/CloudRef.Integration.Tests.csproj
```

Verify the solution builds:

```bash
dotnet build CloudRef.sln
```

Expected: `Build succeeded.` with 0 errors.

---

## Step 4 — Create the Postgres test fixture

Create `tests/integration/CloudRef.Integration.Tests/PostgresFixture.cs`:

```csharp
using CloudRef.Api.Data;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Testcontainers.PostgreSql;

namespace CloudRef.Integration.Tests;

public class PostgresFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _container = new PostgreSqlBuilder()
        .WithImage("postgres:16")
        .WithDatabase("testdb")
        .WithUsername("testuser")
        .WithPassword("testpassword")
        .Build();

    public HttpClient Client { get; private set; } = null!;
    public WebApplicationFactory<Program> Factory { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        await _container.StartAsync();

        Factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder =>
            {
                builder.UseEnvironment("Testing");
                builder.ConfigureServices(services =>
                {
                    // Remove the existing DbContext registration
                    var descriptor = services.SingleOrDefault(
                        d => d.ServiceType == typeof(DbContextOptions<AppDbContext>));
                    if (descriptor != null) services.Remove(descriptor);

                    // Register against the Testcontainers instance
                    services.AddDbContext<AppDbContext>(options =>
                        options.UseNpgsql(_container.GetConnectionString()));
                });
            });

        // Apply migrations to the test container
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        await db.Database.MigrateAsync();

        Client = Factory.CreateClient();
    }

    public async Task DisposeAsync()
    {
        await Factory.DisposeAsync();
        await _container.DisposeAsync();
    }
}
```

---

## Step 5 — Write the integration tests

Create `tests/integration/CloudRef.Integration.Tests/ProductsEndpointTests.cs`:

```csharp
using System.Net;
using System.Net.Http.Json;
using CloudRef.Api.Data;
using CloudRef.Api.Domain;
using Microsoft.Extensions.DependencyInjection;

namespace CloudRef.Integration.Tests;

public class ProductsEndpointTests(PostgresFixture fixture) : IClassFixture<PostgresFixture>
{
    private readonly HttpClient _client = fixture.Client;

    [Fact]
    public async Task GetAll_ReturnsOk_WhenTableIsEmpty()
    {
        var response = await _client.GetAsync("/api/products");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Create_ReturnsCreated_AndPersists()
    {
        var product = new Product { Name = "Widget", Description = "A test widget", Price = 9.99m };

        var createResponse = await _client.PostAsJsonAsync("/api/products", product);
        Assert.Equal(HttpStatusCode.Created, createResponse.StatusCode);

        var created = await createResponse.Content.ReadFromJsonAsync<Product>();
        Assert.NotNull(created);
        Assert.True(created!.Id > 0);

        var getResponse = await _client.GetAsync($"/api/products/{created.Id}");
        Assert.Equal(HttpStatusCode.OK, getResponse.StatusCode);
    }

    [Fact]
    public async Task Update_ReturnsNoContent_AndChangesAreVisible()
    {
        var product = new Product { Name = "Old Name", Price = 1.00m };
        var createResponse = await _client.PostAsJsonAsync("/api/products", product);
        var created = await createResponse.Content.ReadFromJsonAsync<Product>();

        created!.Name = "New Name";
        var updateResponse = await _client.PutAsJsonAsync($"/api/products/{created.Id}", created);
        Assert.Equal(HttpStatusCode.NoContent, updateResponse.StatusCode);

        var getResponse = await _client.GetFromJsonAsync<Product>($"/api/products/{created.Id}");
        Assert.Equal("New Name", getResponse!.Name);
    }

    [Fact]
    public async Task Delete_ReturnsNoContent_AndResourceIsGone()
    {
        var product = new Product { Name = "To Delete", Price = 0.01m };
        var createResponse = await _client.PostAsJsonAsync("/api/products", product);
        var created = await createResponse.Content.ReadFromJsonAsync<Product>();

        var deleteResponse = await _client.DeleteAsync($"/api/products/{created!.Id}");
        Assert.Equal(HttpStatusCode.NoContent, deleteResponse.StatusCode);

        var getResponse = await _client.GetAsync($"/api/products/{created.Id}");
        Assert.Equal(HttpStatusCode.NotFound, getResponse.StatusCode);
    }

    [Fact]
    public async Task GetById_ReturnsNotFound_ForNonExistentId()
    {
        var response = await _client.GetAsync("/api/products/99999");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task MigrationRunsIdempotently()
    {
        using var scope = fixture.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var ex = await Record.ExceptionAsync(() => db.Database.MigrateAsync());
        Assert.Null(ex);
    }
}
```

---

## Step 6 — Add the CI job

Add to `.github/workflows/ci.yml` after the `terraform-localstack` job:

```yaml
  integration-tests:
    name: Integration tests (PostgreSQL via Testcontainers)
    runs-on: [self-hosted, linux, discworld]
    needs: scaffold-check

    env:
      ASPNETCORE_ENVIRONMENT: Testing
      DOTNET_NOLOGO: true

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run integration tests
        run: |
          dotnet test tests/integration/CloudRef.Integration.Tests/ \
            --configuration Release \
            --logger "console;verbosity=normal"
```

> **Note:** No `dotnet restore` or SDK install step — .NET 8 is pre-installed on DISCWORLD. Testcontainers pulls `postgres:16` from Docker Hub on the first run (cached afterward). The runner needs outbound internet access for the first run only.

---

## Step 7 — Commit and push

From the repo root on **MIDDLEEARTH**:

```bash
git add \
  src/backend/CloudRef.Api/Controllers/ProductsController.cs \
  tests/integration/ \
  CloudRef.sln \
  .github/workflows/ci.yml

git commit -m "feat(backend): Products CRUD endpoints + Testcontainers integration tests"
git push
```

Watch the **Actions** tab on GitHub. Two jobs will run:

- `scaffold-check` — on GitHub-hosted runner, verifies directory structure
- `integration-tests` — on self-hosted DISCWORLD runner, spins up PostgreSQL container and runs the 6 tests

**Pause point reached** when both jobs show green checkmarks.

---

## How to Verify

| Check | What to look for |
|---|---|
| `dotnet build CloudRef.sln` | `Build succeeded.` with 0 errors |
| Run tests locally | `dotnet test tests/integration/CloudRef.Integration.Tests/` — all 6 tests pass (requires PostgreSQL running on DISCWORLD) |
| GitHub Actions → `integration-tests` job | All steps green, 6 tests passing |
| Swagger UI | `dotnet run` from `src/backend/CloudRef.Api/`, browse to `http://localhost:5000/swagger` — 5 endpoints listed |

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `No service for type 'DbContextOptions<AppDbContext>'` during startup | `public partial class Program {}` missing | Add it at the bottom of `Program.cs` |
| `Address already in use: 5432` in Testcontainers | Static port mapping conflicting with DISCWORLD's PostgreSQL | Testcontainers uses a random host port by default — do not add `.WithPortBinding(5432)` to the builder |
| Tests pass locally but fail in CI | Connection string pointing at DISCWORLD instead of Testcontainers | Confirm `ASPNETCORE_ENVIRONMENT=Testing` is set in the CI job and the fixture overrides the DbContext registration |
| `Docker not found` on self-hosted runner | Docker not installed or not on PATH for runner user | Verify Docker is installed on DISCWORLD and the runner user is in the `docker` group |
| `postgres:16` pull fails in CI | No outbound internet on first run | The runner needs outbound internet for Docker Hub access on first run only; subsequent runs use the local image cache |
| `MigrateAsync is idempotent` test fails | Migration history table corrupted or duplicate migration names | `dotnet ef migrations remove` and re-add with a clean name |
| Build fails with `CS0246: type not found` | Project reference missing | Confirm `dotnet add reference` was run from the test project directory |

---

## AWS Equivalent

The integration tests run against Testcontainers in both local development and CI — no RDS instance is needed for the test suite. In a production AWS pipeline:

- The same Testcontainers tests run in GitHub Actions as a quality gate
- A separate staging environment uses RDS, exercised by Playwright E2E tests (Phase 12)
- No changes to test code are required for AWS — only the `DefaultConnection` environment variable changes

---

## Further Reading

- [Testcontainers for .NET](https://dotnet.testcontainers.org/)
- [EF Core migrations in tests](https://learn.microsoft.com/en-us/ef/core/testing/testing-with-the-database)
- [WebApplicationFactory in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/test/integration-tests)
- [xUnit IClassFixture pattern](https://xunit.net/docs/shared-context)
