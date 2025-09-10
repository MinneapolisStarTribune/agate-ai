# Neo4j Schema

This document describes the nodes, properties, relationships, and database constraints/indexes for the Neo4j graph used by this application.

## Nodes

### Article
- uuid (string, primary key)
- fk_id (string)
- headline (string)
- url (string)
- author (string)
- pub_date (string)
- story_type (string)

### Location
- uuid (string, primary key)
- name (string)
- original_text (string)
- type (string)
- importance (string)
- description (string)
- latitude (float)
- longitude (float)

## Relationships

- (l:Location)-[:MENTIONED_IN]->(a:Article)

## Constraints & Indexes

Use the following Cypher statements to create constraints and indexes. Adjust syntax for your Neo4j version if needed.

```cypher
// Unique constraints on primary identifiers
CREATE CONSTRAINT ON (a:Article) ASSERT a.uuid IS UNIQUE;
CREATE CONSTRAINT ON (l:Location) ASSERT l.uuid IS UNIQUE;

// Indexes for faster lookups
CREATE INDEX ON :Article(url);
CREATE INDEX ON :Location(name);
```