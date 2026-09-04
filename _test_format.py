# -*- coding: utf-8 -*-
"""pipeline_capture.format_markdown 的离线格式自测。"""
from extract_capture import parse_frontmatter
from pipeline_capture import Capture, format_markdown


def main() -> None:
    capture = Capture(
        title='AI 学习：我的 "高效" 清单',
        author="游牧岛NEXT",
        published_at="2026-07-02 20:24:38 +0800",
        body=(
            "先从一个具体问题开始。\t\n\n\n"
            "把方法真正用起来。\n\n"
            "#AI学习[话题]# #效率工具[话题]#"
        ),
        interactions="1.2万赞 / 3万藏 / 200评 / 5分享",
        comments=[
            "JJ学姐泰学记<br>点赞关注<br>6天前湖南<br>赞<br>1",
            "AI 超个体孵化器<br>收藏了，筛选过就是不一样<br>08-08美国<br>赞<br>1",
            "朱古力小姐🍫<br>这些博主是什么平台的？<br>昨天 13:22广东",
        ],
        content_type="图文",
    )
    output = format_markdown(
        capture,
        "xhs",
        "https://www.xiaohongshu.com/explore/example",
    )
    print(output, end="")

    assert "likes: 12000" in output
    assert "favorites: 30000" in output
    assert "  - AI学习" in output and "  - 效率工具" in output
    assert "[话题]" not in output
    assert "\t" not in output
    assert "6天前·湖南" in output
    assert "昨天 13:22·广东" in output
    metadata, parsed_body = parse_frontmatter(output)
    assert metadata["title"] == 'AI 学习：我的 "高效" 清单'
    assert metadata["likes"] == "12000"
    assert metadata["tags"] == ["AI学习", "效率工具"]
    assert "## 正文" in parsed_body


if __name__ == "__main__":
    main()
