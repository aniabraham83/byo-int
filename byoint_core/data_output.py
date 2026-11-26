import all_connects
import json
import os
import re
_FEED_CACHE_PREFIX = "feed:output:"


def _get_feed_cache_ttl_seconds():
    try:
        return max(0, int(os.getenv("FEED_CACHE_TTL_SECONDS", "120")))
    except Exception:
        return 120


def _get_redis_client():
    return all_connects.get_redis_client(socket_timeout=1, socket_connect_timeout=1)


def _feed_cache_key(output_name):
    return f"{_FEED_CACHE_PREFIX}{str(output_name).strip()}"


def _read_feed_from_cache(output_name):
    client = _get_redis_client()
    if not client:
        return None
    try:
        cached_value = client.get(_feed_cache_key(output_name))
        if not cached_value:
            return None
        return json.loads(cached_value)
    except Exception:
        return None


def _write_feed_to_cache(output_name, payload):
    client = _get_redis_client()
    if not client:
        return False
    try:
        ttl_seconds = _get_feed_cache_ttl_seconds()
        cache_key = _feed_cache_key(output_name)
        cache_payload = json.dumps(payload)
        if ttl_seconds > 0:
            client.setex(cache_key, ttl_seconds, cache_payload)
        else:
            client.set(cache_key, cache_payload)
        return True
    except Exception:
        return False


def invalidate_output_feed_cache(output_name):
    if not output_name:
        return False
    client = _get_redis_client()
    if not client:
        return False
    try:
        client.delete(_feed_cache_key(output_name))
        return True
    except Exception:
        return False


def invalidate_all_output_feed_caches():
    client = _get_redis_client()
    if not client:
        return 0
    try:
        keys = list(client.scan_iter(match=f"{_FEED_CACHE_PREFIX}*"))
        if not keys:
            return 0
        return int(client.delete(*keys) or 0)
    except Exception:
        return 0


def _is_enabled_output(output_doc):
    enabled_value = output_doc.get("enabled")
    return enabled_value in [True, "Y", "true", 1] or enabled_value is None


def _extract_filter_sources(filter_value):
    names = []

    def collect_source_names(node):
        if isinstance(node, dict):
            if "source_name" in node and node.get("source_name"):
                names.append(str(node.get("source_name")).strip())
            for value in node.values():
                collect_source_names(value)
        elif isinstance(node, list):
            for item in node:
                collect_source_names(item)

    if filter_value is None:
        return names

    if isinstance(filter_value, (dict, list)):
        collect_source_names(filter_value)
        return list(dict.fromkeys([n for n in names if n]))

    filter_text = str(filter_value).strip()
    if not filter_text:
        return names

    try:
        parsed_json = json.loads(filter_text)
        collect_source_names(parsed_json)
        parsed_names = list(dict.fromkeys([n for n in names if n]))
        if parsed_names:
            return parsed_names
    except Exception:
        pass

    return [s.strip() for s in filter_text.split(',') if s.strip()]


def _extract_filter_criteria(filter_value):
    criteria = {
        "source_name": [],
        "selected_tags": [],
        "selected_tags_not": [],
        "selected_enrichments": [],
        "selected_enrichment_values": [],
        "selected_br_scores": [],
    }

    def add_values(target_key, raw_value):
        if raw_value is None:
            return
        if isinstance(raw_value, list):
            for item in raw_value:
                text = str(item).strip()
                if text:
                    criteria[target_key].append(text)
            return
        text = str(raw_value).strip()
        if text:
            criteria[target_key].append(text)

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key or "").strip().lower()
                if key_text == "source_name":
                    add_values("source_name", value)
                elif key_text in ["selected_tags", "tags"]:
                    add_values("selected_tags", value)
                elif key_text in ["selected_tags_not", "tags_not", "excluded_tags", "not_tags"]:
                    add_values("selected_tags_not", value)
                elif key_text in ["selected_enrichments", "enrichments"]:
                    add_values("selected_enrichments", value)
                elif key_text in ["selected_enrichment_values", "enrichment_values"]:
                    add_values("selected_enrichment_values", value)
                elif key_text in ["selected_br_scores", "br_scores", "br_score"]:
                    add_values("selected_br_scores", value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    if filter_value is None:
        return criteria

    if isinstance(filter_value, (dict, list)):
        collect(filter_value)
    else:
        filter_text = str(filter_value).strip()
        if not filter_text:
            return criteria

        try:
            parsed_json = json.loads(filter_text)
            collect(parsed_json)
        except Exception:
            criteria["source_name"].extend([s.strip() for s in filter_text.split(',') if s.strip()])

    for key in criteria:
        criteria[key] = list(dict.fromkeys([value for value in criteria[key] if value]))

    return criteria


def _extract_source_names(sources_field):
    names = []
    if isinstance(sources_field, list):
        for src in sources_field:
            if isinstance(src, dict):
                src_name = src.get("source_name")
                if src_name:
                    names.append(str(src_name).strip())
            elif isinstance(src, str):
                names.append(src.strip())
    elif isinstance(sources_field, dict):
        src_name = sources_field.get("source_name")
        if src_name:
            names.append(str(src_name).strip())
    elif isinstance(sources_field, str):
        names.append(sources_field.strip())
    return names


def _extract_indicator_tags(sources_field):
    tags = []

    if not isinstance(sources_field, list):
        return tags

    for src in sources_field:
        if not isinstance(src, dict):
            continue

        raw_tags = src.get("tag") if "tag" in src else src.get("tags")
        if isinstance(raw_tags, list):
            for raw_tag in raw_tags:
                tag_value = str(raw_tag).strip()
                if tag_value:
                    tags.append(tag_value)
        elif raw_tags is not None:
            for raw_tag in str(raw_tags).split(','):
                tag_value = raw_tag.strip()
                if tag_value:
                    tags.append(tag_value)

    # Preserve order while removing duplicates
    return list(dict.fromkeys(tags))


def _normalize_br_score_value(raw_score):
    if raw_score in [None, '']:
        return ''

    try:
        numeric = float(raw_score)
        if numeric.is_integer():
            return str(int(numeric))
        return str(numeric)
    except Exception:
        return str(raw_score).strip()


def _extract_indicator_br_scores(sources_field):
    br_scores = []

    if not isinstance(sources_field, list):
        return br_scores

    for src in sources_field:
        if not isinstance(src, dict):
            continue

        normalized_score = _normalize_br_score_value(src.get("br_score"))
        if normalized_score:
            br_scores.append(normalized_score)

    return list(dict.fromkeys(br_scores))


def _extract_indicator_enrichment_fields(enrichment_field):
    fields = []

    if not isinstance(enrichment_field, dict):
        return fields

    for field_name in enrichment_field.keys():
        text = str(field_name).strip()
        if text:
            fields.append(text)

    return list(dict.fromkeys(fields))


def _extract_indicator_enrichment_values(enrichment_field):
    values = []

    def collect(node):
        if isinstance(node, dict):
            if "value" in node:
                collect(node.get("value"))
                return
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif node is not None:
            text = str(node).strip()
            if text:
                values.append(text)

    collect(enrichment_field)
    return list(dict.fromkeys(values))


def get_distinct_enrichment_values(limit=500):
    """Return sorted list of distinct enrichment values stored across all indicators."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        values_set = set()
        for doc in indicators.find(
            {"data-enrichment": {"$exists": True}},
            {"data-enrichment": 1}
        ):
            for v in _extract_indicator_enrichment_values(doc.get("data-enrichment")):
                text = str(v).strip()
                if text:
                    values_set.add(text)
                if len(values_set) >= limit:
                    break
        mongo_client.close()
        return sorted(list(values_set), key=lambda x: x.lower()), None
    except Exception as e:
        return [], str(e)


def get_filter_options_for_sources(source_names, enrich_value_limit=500):
    """Return tags, enrichments, BR scores, and enrichment values scoped to source_names."""
    if not source_names:
        return {
            "tags": [],
            "enrichments": [],
            "br_scores": [],
            "enrichment_values": [],
            "enrichment_values_by_field": {}
        }, None

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        core_db = mongo_client["byoint_core_data"]
        indicators = core_db["indicators"]

        tags_set = set()
        enrichments_set = set()
        br_scores_set = set()
        enrichment_values_by_field = {}


        # Derive all filter options directly from indicators belonging to selected sources.
        values_set = set()
        for doc in indicators.find(
            {"sources.source_name": {"$in": list(source_names)}},
            {"sources": 1, "data-enrichment": 1}
        ):
            for tag in _extract_indicator_tags(doc.get("sources")):
                tag_text = str(tag).strip()
                if tag_text:
                    tags_set.add(tag_text)

            for score in _extract_indicator_br_scores(doc.get("sources")):
                score_text = _normalize_br_score_value(score)
                if score_text:
                    br_scores_set.add(score_text)

            enrichment_obj = doc.get("data-enrichment")
            for field_name in _extract_indicator_enrichment_fields(enrichment_obj):
                field_text = str(field_name).strip()
                if field_text:
                    enrichments_set.add(field_text)

                    field_values_set = enrichment_values_by_field.setdefault(field_text, set())
                    field_payload = {}
                    if isinstance(enrichment_obj, dict):
                        field_payload = enrichment_obj.get(field_name)
                    for field_value in _extract_indicator_enrichment_values(field_payload):
                        field_value_text = str(field_value).strip()
                        if field_value_text:
                            field_values_set.add(field_value_text)

            for v in _extract_indicator_enrichment_values(doc.get("data-enrichment")):
                text = str(v).strip()
                if text:
                    values_set.add(text)
                if len(values_set) >= enrich_value_limit:
                    break

        mongo_client.close()
        return {
            "tags": sorted(list(tags_set), key=lambda x: x.lower()),
            "enrichments": sorted(list(enrichments_set), key=lambda x: x.lower()),
            "br_scores": sorted(list(br_scores_set), key=lambda x: float(x) if str(x).replace('.', '', 1).isdigit() else str(x).lower()),
            "enrichment_values": sorted(list(values_set), key=lambda x: x.lower()),
            "enrichment_values_by_field": {
                field: sorted(list(value_set), key=lambda x: x.lower())
                for field, value_set in enrichment_values_by_field.items()
            }
        }, None
    except Exception as e:
        return {
            "tags": [],
            "enrichments": [],
            "br_scores": [],
            "enrichment_values": [],
            "enrichment_values_by_field": {}
        }, str(e)


def _load_enrichment_output_fields(selected_enrichment_names):
    if not selected_enrichment_names:
        return set()

    return {
        str(name).strip().lower()
        for name in selected_enrichment_names
        if str(name).strip()
    }


def _load_disallow_guardrails_map(mongo_client):
    category_map = {}
    try:
        config_db = mongo_client["byoint_core_config"]
        guardrails_col = config_db["output_guardrails"]
        cursor = guardrails_col.find({"action": "disallow"}, {"output_category": 1, "tag": 1})
        for rule in cursor:
            category = str(rule.get("output_category") or "general").strip().lower()
            tag_value = str(rule.get("tag") or "").strip().lower()
            if not category or not tag_value:
                continue
            category_map.setdefault(category, set()).add(tag_value)
    except Exception:
        return {}
    return category_map


def _build_indicator_query(output_source, filter_criteria, disallowed_tags_for_category=None):
    disallowed_tags_for_category = set(disallowed_tags_for_category or set())

    source_filters = []
    if isinstance(output_source, list):
        source_filters.extend([str(s).strip() for s in output_source if str(s).strip()])
    elif output_source:
        source_filters.append(str(output_source).strip())

    source_filters.extend(filter_criteria.get("source_name") or [])
    source_filters = list(dict.fromkeys([s for s in source_filters if s]))

    normalized_tag_filters = {
        str(tag).strip().lower()
        for tag in (filter_criteria.get("selected_tags") or [])
        if str(tag).strip()
    }
    normalized_excluded_tag_filters = {
        str(tag).strip().lower()
        for tag in (filter_criteria.get("selected_tags_not") or [])
        if str(tag).strip()
    }
    normalized_enrichment_filters = {
        str(enrichment).strip().lower()
        for enrichment in (filter_criteria.get("selected_enrichments") or [])
        if str(enrichment).strip()
    }
    normalized_enrichment_value_filters = {
        str(value).strip().lower()
        for value in (filter_criteria.get("selected_enrichment_values") or [])
        if str(value).strip()
    }
    normalized_br_score_filters = {
        _normalize_br_score_value(value).lower()
        for value in (filter_criteria.get("selected_br_scores") or [])
        if _normalize_br_score_value(value)
    }
    enrichment_output_fields = _load_enrichment_output_fields(normalized_enrichment_filters)

    query = {"active": True}
    and_conditions = []

    if source_filters:
        query["sources.source_name"] = {"$in": source_filters}

    if normalized_tag_filters:
        tag_clauses = [
            {"sources.tag": {"$regex": f"^{re.escape(tag)}$", "$options": "i"}}
            for tag in sorted(list(normalized_tag_filters))
        ]
        if tag_clauses:
            and_conditions.append({"$or": tag_clauses})

    if normalized_excluded_tag_filters:
        exclude_tag_clauses = [
            {"sources.tag": {"$regex": f"^{re.escape(tag)}$", "$options": "i"}}
            for tag in sorted(list(normalized_excluded_tag_filters))
        ]
        if exclude_tag_clauses:
            and_conditions.append({"$nor": exclude_tag_clauses})

    if normalized_br_score_filters:
        br_score_clauses = []
        for score in sorted(list(normalized_br_score_filters)):
            br_score_clauses.append({"sources.br_score": score})
            try:
                numeric = float(score)
                br_score_clauses.append({"sources.br_score": int(numeric) if numeric.is_integer() else numeric})
            except Exception:
                pass
        if br_score_clauses:
            and_conditions.append({"$or": br_score_clauses})

    if enrichment_output_fields:
        enrichment_field_exists_clauses = [
            {f"data-enrichment.{field_name}": {"$exists": True}}
            for field_name in sorted(list(enrichment_output_fields))
        ]
        if enrichment_field_exists_clauses:
            and_conditions.append({"$or": enrichment_field_exists_clauses})

    if normalized_enrichment_value_filters and enrichment_output_fields:
        value_clauses = []
        for field_name in sorted(list(enrichment_output_fields)):
            field_path = f"data-enrichment.{field_name}.value"
            for value in sorted(list(normalized_enrichment_value_filters)):
                value_clauses.append({field_path: {"$regex": f"^{re.escape(value)}$", "$options": "i"}})
        if value_clauses:
            and_conditions.append({"$or": value_clauses})

    if disallowed_tags_for_category:
        disallow_clauses = [
            {"sources.tag": {"$regex": f"^{re.escape(tag)}$", "$options": "i"}}
            for tag in sorted(list(disallowed_tags_for_category))
        ]
        if disallow_clauses:
            and_conditions.append({"$nor": disallow_clauses})

    if and_conditions:
        query["$and"] = and_conditions

    return {
        "query": query,
        "source_filters": source_filters,
        "normalized_tag_filters": normalized_tag_filters,
        "normalized_excluded_tag_filters": normalized_excluded_tag_filters,
        "normalized_enrichment_filters": normalized_enrichment_filters,
        "normalized_enrichment_value_filters": normalized_enrichment_value_filters,
        "normalized_br_score_filters": normalized_br_score_filters,
        "enrichment_output_fields": enrichment_output_fields,
    }


def get_indicator_query_preview(output_source=None, filter_search=None, output_category="general"):
    mongo_client = None
    try:
        disallow_guardrails_map = {}
        mongo_client, _ = all_connects.connect_mongodb()
        disallow_guardrails_map = _load_disallow_guardrails_map(mongo_client)
        category = str(output_category or "general").strip().lower()
        disallowed_tags_for_category = set((disallow_guardrails_map or {}).get(category, set()))
        filter_criteria = _extract_filter_criteria(filter_search)
        query_parts = _build_indicator_query(output_source, filter_criteria, disallowed_tags_for_category)
        return query_parts.get("query", {"active": True}), None
    except Exception as e:
        return {"active": True}, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def _build_output_result(output, indicators, disallow_guardrails_map=None):
    output_name = output.get("name")
    output_source = output.get("source_name")
    output_type = output.get("type") or output.get("output_type")
    filter_search = output.get("filter_search")
    output_category = str(output.get("output_category") or "general").strip().lower()
    disallowed_tags_for_category = set((disallow_guardrails_map or {}).get(output_category, set()))

    filter_criteria = _extract_filter_criteria(filter_search)

    query_parts = _build_indicator_query(output_source, filter_criteria, disallowed_tags_for_category)
    indicator_query = query_parts.get("query", {"active": True})
    source_filters = query_parts.get("source_filters") or []
    normalized_tag_filters = query_parts.get("normalized_tag_filters") or set()
    normalized_excluded_tag_filters = query_parts.get("normalized_excluded_tag_filters") or set()
    normalized_enrichment_value_filters = query_parts.get("normalized_enrichment_value_filters") or set()
    normalized_br_score_filters = query_parts.get("normalized_br_score_filters") or set()
    enrichment_output_fields = query_parts.get("enrichment_output_fields") or set()

    iplist = []
    for e_record in indicators.find(indicator_query):
        if normalized_tag_filters:
            indicator_tags = {
                str(tag).strip().lower()
                for tag in _extract_indicator_tags(e_record.get("sources"))
                if str(tag).strip()
            }
            if not indicator_tags or indicator_tags.isdisjoint(normalized_tag_filters):
                continue

        if normalized_excluded_tag_filters:
            indicator_tags = {
                str(tag).strip().lower()
                for tag in _extract_indicator_tags(e_record.get("sources"))
                if str(tag).strip()
            }
            if indicator_tags and not indicator_tags.isdisjoint(normalized_excluded_tag_filters):
                continue

        if enrichment_output_fields:
            enrichment_obj = e_record.get("data-enrichment")
            indicator_enrichment_fields = {
                str(field_name).strip().lower()
                for field_name in _extract_indicator_enrichment_fields(enrichment_obj)
                if str(field_name).strip()
            }
            if not indicator_enrichment_fields or indicator_enrichment_fields.isdisjoint(enrichment_output_fields):
                continue

        if normalized_enrichment_value_filters:
            enrichment_obj = e_record.get("data-enrichment")
            indicator_enrichment_values = {
                str(value).strip().lower()
                for value in _extract_indicator_enrichment_values(enrichment_obj)
                if str(value).strip()
            }
            if not indicator_enrichment_values or indicator_enrichment_values.isdisjoint(normalized_enrichment_value_filters):
                continue

        if normalized_br_score_filters:
            indicator_br_scores = {
                _normalize_br_score_value(score).lower()
                for score in _extract_indicator_br_scores(e_record.get("sources"))
                if _normalize_br_score_value(score)
            }
            if not indicator_br_scores or indicator_br_scores.isdisjoint(normalized_br_score_filters):
                continue

        if disallowed_tags_for_category:
            indicator_tags = {
                str(tag).strip().lower()
                for tag in _extract_indicator_tags(e_record.get("sources"))
                if str(tag).strip()
            }
            if indicator_tags and not indicator_tags.isdisjoint(disallowed_tags_for_category):
                continue

        ip_value = e_record.get("value")
        if ip_value:
            iplist.append(str(ip_value))

    return {
        "name": output_name,
        "source_name": output_source,
        "type": output_type,
        "enabled": output.get("enabled", False),
        "feed_authentication_status": bool(output.get("feed_authentication_status", False)),
        "filter_search": filter_search,
        "source_filters": source_filters,
        "indicator_count": len(iplist),
        "entries": iplist,
        "edl": "</br>".join(iplist)
    }




def output_edl(source=None):
    mongo_client = None
    try:
        results = []
        mongo_client, _ = all_connects.connect_mongodb()
        
        db = mongo_client["byoint_core_data"] 
        outputs = db["outputs"]
        indicators = db["indicators"]
        disallow_guardrails_map = _load_disallow_guardrails_map(mongo_client)

        for output in outputs.find({}):
            if not _is_enabled_output(output):
                continue
            if source and str(output.get("source_name") or "").strip() != str(source).strip():
                continue
            results.append(_build_output_result(output, indicators, disallow_guardrails_map))

        return results

    except Exception as e:
        print (e)
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def output_edl_by_name(output_name):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        outputs = db["outputs"]
        indicators = db["indicators"]
        disallow_guardrails_map = _load_disallow_guardrails_map(mongo_client)

        output = outputs.find_one({"name": output_name})
        if not output:
            return None
        if not _is_enabled_output(output):
            return None

        return _build_output_result(output, indicators, disallow_guardrails_map)
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def output_edl_by_name_cached(output_name):
    cached_payload = _read_feed_from_cache(output_name)
    if cached_payload is not None:
        return cached_payload

    payload = output_edl_by_name(output_name)
    if payload:
        _write_feed_to_cache(output_name, payload)
    return payload


def refresh_output_feed_cache():
    if not _get_redis_client():
        return 0

    refreshed = 0
    for output_row in output_edl():
        output_name = output_row.get("name")
        if not output_name:
            continue
        if _write_feed_to_cache(output_name, output_row):
            refreshed += 1
    return refreshed