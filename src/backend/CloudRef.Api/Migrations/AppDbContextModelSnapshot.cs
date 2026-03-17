using System;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;

namespace CloudRef.Api.Migrations;

[DbContext(typeof(CloudRef.Api.Data.AppDbContext))]
partial class AppDbContextModelSnapshot : ModelSnapshot
{
    protected override void BuildModel(ModelBuilder modelBuilder)
    {
        modelBuilder
            .HasAnnotation("Relational:MaxIdentifierLength", 63)
            .HasAnnotation("ProductVersion", "8.0.0");

        modelBuilder.Entity("CloudRef.Api.Domain.Product", b =>
        {
            b.Property<int>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("integer");

            b.Property<DateTime>("CreatedAt")
                .HasColumnType("timestamp with time zone");

            b.Property<string>("Description")
                .HasColumnType("character varying(1000)")
                .HasMaxLength(1000);

            b.Property<string>("Name")
                .IsRequired()
                .HasMaxLength(200)
                .HasColumnType("character varying(200)");

            b.Property<decimal>("Price")
                .HasColumnType("numeric(18,2)");

            b.HasKey("Id");

            b.ToTable("Products");
        });
    }
}
