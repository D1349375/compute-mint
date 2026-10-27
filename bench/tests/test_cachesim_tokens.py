from bench.cachesim import PrefixCache
from bench.tokens import MESSAGE_OVERHEAD, estimate_tokens, weight


def test_token_estimate_counts_ascii_by_3_5_and_other_characters_one_each():
    assert estimate_tokens("a" * 70) == 20
    assert estimate_tokens("你好世界") == 4
    assert weight("⟨X⟩") == 2 + 1 / 3.5 * 1
    assert estimate_tokens("") == 0


def segs(*texts):
    return [t * 1 for t in texts]


def test_identical_prompt_is_cached_except_the_last_token_block():
    cache = PrefixCache(block_tokens=64)
    prompt = ["tools " * 200, "msg-a " * 400, "msg-b " * 400]
    first, cached_first = cache.lookup_and_insert("m", prompt)
    assert cached_first == 0
    second, cached_second = cache.lookup_and_insert("m", prompt)
    assert second == first and 0 < cached_second < second
    assert cached_second % 64 == 0


def test_appending_a_message_reuses_the_whole_previous_prompt():
    cache = PrefixCache(block_tokens=64)
    base = ["tools " * 200, "msg-a " * 400]
    prompt_a, _ = cache.lookup_and_insert("m", base)
    prompt_b, cached = cache.lookup_and_insert("m", base + ["msg-b " * 100])
    assert abs(cached - prompt_a) <= 64
    assert prompt_b > prompt_a


def test_changing_an_early_segment_loses_the_cache_from_that_point():
    cache = PrefixCache(block_tokens=64)
    cache.lookup_and_insert("m", ["tools " * 200, "msg-a " * 400, "msg-b " * 400])
    _, cached = cache.lookup_and_insert("m", ["tools " * 200, "msg-X " * 400, "msg-b " * 400])
    tools_tokens = weight("tools " * 200) + MESSAGE_OVERHEAD
    # the shared first segment and the common characters ("msg-") of the changed one
    assert tools_tokens - 64 <= cached <= tools_tokens + 64


def test_partial_match_inside_a_segment_counts_the_common_characters():
    cache = PrefixCache(block_tokens=1)
    cache.lookup_and_insert("m", ["x" * 3500 + "A" * 3500])
    _, cached = cache.lookup_and_insert("m", ["x" * 3500 + "B" * 3500])
    assert 990 <= cached <= 1000   # 3500 characters / 3.5


def test_models_do_not_share_entries_and_prefixes_are_shared_across_conversations():
    cache = PrefixCache(block_tokens=64)
    prompt = ["system " * 300, "task one " * 100]
    cache.lookup_and_insert("standard", prompt)
    assert cache.lookup_and_insert("contributor", prompt)[1] == 0
    other_task = ["system " * 300, "a completely different task " * 100]
    assert cache.lookup_and_insert("standard", other_task)[1] > 0   # same system prompt prefix


def test_at_least_one_token_is_never_cached():
    cache = PrefixCache(block_tokens=1)
    prompt = ["abc " * 50]
    cache.lookup_and_insert("m", prompt)
    total, cached = cache.lookup_and_insert("m", prompt)
    assert cached == total - 1
