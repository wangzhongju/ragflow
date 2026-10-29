---
sidebar_position: 3
title: Switch Document Engine
sidebar_label: Switch Document Engine
slug: /switch_doc_engine
sidebar_custom_props: {
  categoryIcon: LucideShuffle
}
---
# Document engine selection

The deployed 91/92 environment uses Elasticsearch. Changing the engine requires a reviewed data migration or reindexing plan; changing `DOC_ENGINE` alone does not move existing vectors or indexes. Do not delete existing storage volumes to switch engines.

The CI multi-backend definitions remain in `docker/ci/compose.base.yml`, with defaults in `docker/ci/env.example`. They test Elasticsearch, Infinity and other backends independently of the business deployment. For production configuration and backups, use the [operations manual](../operations.html).
