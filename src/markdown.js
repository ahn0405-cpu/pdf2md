/* 미리보기용 소형 마크다운 렌더러.
   외부 라이브러리 없이 동작하도록 필요한 문법만 다룬다:
   제목 / 문단 / 목록(중첩) / 표 / 코드블록 / 인용 / 수평선 / 이미지 / 링크 /
   굵게·기울임·인라인코드. 출력 HTML은 직접 조립하며 원문은 모두 이스케이프한다. */
/* (ES 모듈) */

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // 링크는 허용 스킴만 통과시킨다. PDF 주석에 담겨 오는 주소라 신뢰할 수 없다.
  function safeUrl(url) {
    var u = String(url || '').trim();
    if (/^[a-z][a-z0-9+.-]*:/i.test(u) && !/^(https?|mailto|tel):/i.test(u)) return '#';
    return u;
  }

  // 이미지는 추출 자산(상대 경로)이나 data: 이미지라서 규칙이 다르다.
  function safeImageUrl(url) {
    var u = String(url || '').trim();
    if (/^data:image\//i.test(u)) return u;
    if (/^[a-z][a-z0-9+.-]*:/i.test(u) && !/^https?:/i.test(u)) return '';
    return u;
  }

  // ---- 인라인 -------------------------------------------------------------
  function inline(src, resolve) {
    var out = '';
    var i = 0;

    while (i < src.length) {
      var ch = src[i];

      // 이스케이프
      if (ch === '\\' && i + 1 < src.length) { out += esc(src[i + 1]); i += 2; continue; }

      // 인라인 코드 (백틱 개수 일치)
      if (ch === '`') {
        var open = 0;
        while (src[i + open] === '`') open++;
        var fence = src.substr(i, open);
        var end = src.indexOf(fence, i + open);
        if (end !== -1) {
          out += '<code>' + esc(src.slice(i + open, end)) + '</code>';
          i = end + open;
          continue;
        }
      }

      // 이미지 / 링크
      if (ch === '!' && src[i + 1] === '[') {
        var img = matchLink(src, i + 1);
        if (img) {
          out += '<img src="' + esc(safeImageUrl(resolve ? resolve(img.url) : img.url)) +
                 '" alt="' + esc(img.text) + '">';
          i = img.end;
          continue;
        }
      }
      if (ch === '[') {
        var lnk = matchLink(src, i);
        if (lnk) {
          out += '<a href="' + esc(safeUrl(lnk.url)) + '" target="_blank" rel="noopener">' +
                 inline(lnk.text, resolve) + '</a>';
          i = lnk.end;
          continue;
        }
      }

      // 강조
      if (ch === '*' || ch === '_') {
        var run = 0;
        while (src[i + run] === ch) run++;
        var marker = src.substr(i, Math.min(run, 3));
        var close = src.indexOf(marker, i + marker.length);
        if (close !== -1 && close > i + marker.length) {
          var body = src.slice(i + marker.length, close);
          var inner = inline(body, resolve);
          if (marker.length >= 3) out += '<strong><em>' + inner + '</em></strong>';
          else if (marker.length === 2) out += '<strong>' + inner + '</strong>';
          else out += '<em>' + inner + '</em>';
          i = close + marker.length;
          continue;
        }
      }

      // 허용 태그 (변환기가 표/줄바꿈에 쓰는 것만)
      if (ch === '<') {
        var tag = /^<\/?(br|table|thead|tbody|tr|th|td|sub|sup)\s*\/?>/i.exec(src.slice(i));
        if (tag) { out += tag[0]; i += tag[0].length; continue; }
      }

      out += esc(ch);
      i++;
    }
    return out;
  }

  function matchLink(src, start) {
    if (src[start] !== '[') return null;
    var depth = 0, i = start;
    for (; i < src.length; i++) {
      if (src[i] === '\\') { i++; continue; }
      if (src[i] === '[') depth++;
      else if (src[i] === ']') { depth--; if (depth === 0) break; }
    }
    if (depth !== 0 || src[i + 1] !== '(') return null;
    var text = src.slice(start + 1, i);
    var j = i + 2, pdepth = 1;
    for (; j < src.length; j++) {
      if (src[j] === '(') pdepth++;
      else if (src[j] === ')') { pdepth--; if (pdepth === 0) break; }
    }
    if (pdepth !== 0) return null;
    return { text: text, url: src.slice(i + 2, j).trim(), end: j + 1 };
  }

  // ---- 블록 ---------------------------------------------------------------
  function render(md, resolve) {
    var lines = String(md || '').replace(/\r\n?/g, '\n').split('\n');
    var html = [];
    var i = 0;

    function isTableSep(s) { return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(s); }
    function cells(row) {
      var r = row.trim().replace(/^\|/, '').replace(/\|$/, '');
      var out = [], cur = '';
      for (var k = 0; k < r.length; k++) {
        if (r[k] === '\\' && r[k + 1] === '|') { cur += '|'; k++; continue; }
        if (r[k] === '|') { out.push(cur); cur = ''; continue; }
        cur += r[k];
      }
      out.push(cur);
      return out.map(function (c) { return c.trim(); });
    }

    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) { i++; continue; }

      // 코드 펜스
      var fence = /^\s*(```+|~~~+)(.*)$/.exec(line);
      if (fence) {
        var mark = fence[1][0].repeat(3);
        var buf = [];
        i++;
        while (i < lines.length && !new RegExp('^\\s*' + mark).test(lines[i])) buf.push(lines[i++]);
        i++;
        html.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>');
        continue;
      }

      // 수평선
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { html.push('<hr>'); i++; continue; }

      // 제목
      var h = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line);
      if (h) {
        html.push('<h' + h[1].length + '>' + inline(h[2].trim(), resolve) + '</h' + h[1].length + '>');
        i++;
        continue;
      }

      // HTML 표 블록 (변환기가 그대로 내보낸 경우)
      if (/^\s*<table/i.test(line)) {
        var tbuf = [];
        while (i < lines.length) { tbuf.push(lines[i]); if (/<\/table>/i.test(lines[i++])) break; }
        html.push(tbuf.join('\n'));
        continue;
      }

      // 표
      if (line.indexOf('|') !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        var head = cells(line);
        i += 2;
        var rows = [];
        while (i < lines.length && lines[i].indexOf('|') !== -1 && lines[i].trim()) rows.push(cells(lines[i++]));
        var t = '<table><thead><tr>' +
          head.map(function (c) { return '<th>' + inline(c, resolve) + '</th>'; }).join('') +
          '</tr></thead><tbody>';
        rows.forEach(function (r) {
          t += '<tr>';
          for (var c = 0; c < head.length; c++) t += '<td>' + inline(r[c] || '', resolve) + '</td>';
          t += '</tr>';
        });
        html.push(t + '</tbody></table>');
        continue;
      }

      // 인용
      if (/^\s*>\s?/.test(line)) {
        var q = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''));
        html.push('<blockquote>' + render(q.join('\n'), resolve) + '</blockquote>');
        continue;
      }

      // 목록
      if (LIST_RE.test(line)) {
        var block = [];
        while (i < lines.length && LIST_RE.test(lines[i])) block.push(lines[i++]);
        html.push(renderList(block, resolve));
        continue;
      }

      // 문단
      var para = [];
      while (i < lines.length && lines[i].trim() &&
             !/^\s{0,3}#{1,6}\s/.test(lines[i]) &&
             !/^\s*(```|~~~)/.test(lines[i]) &&
             !/^\s*>/.test(lines[i]) &&
             !/^\s*([-*_])(\s*\1){2,}\s*$/.test(lines[i]) &&
             !/^(\s*)([-*+]|\d{1,3}[.)])\s+/.test(lines[i]) &&
             !/^\s*<table/i.test(lines[i])) {
        para.push(lines[i++]);
      }
      if (para.length) html.push('<p>' + inline(para.join('\n'), resolve).replace(/\n/g, '<br>') + '</p>');
      else i++;
    }
    return html.join('\n');
  }

  var LIST_RE = /^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/;

  function renderList(block, resolve) {
    // 같은 깊이에서 글머리표 목록과 번호 목록이 이어지면 별개의 목록으로 끊는다.
    var out = '';
    var items = [];
    var ordered = null;

    function flush() {
      if (!items.length) return;
      var tag = ordered ? 'ol' : 'ul';
      out += '<' + tag + '>' + items.join('') + '</' + tag + '>';
      items = [];
    }

    var idx = 0;
    while (idx < block.length) {
      var m = LIST_RE.exec(block[idx]);
      var indent = m[1].length;
      var isOrdered = /\d/.test(m[2]);
      if (ordered !== null && isOrdered !== ordered) flush();
      ordered = isOrdered;

      var content = m[3];
      idx++;
      var nested = [];
      while (idx < block.length) {
        var n = LIST_RE.exec(block[idx]);
        if (n[1].length > indent) nested.push(block[idx++]);
        else break;
      }
      var htmlItem = inline(content, resolve);
      if (nested.length) htmlItem += renderList(nested, resolve);
      items.push('<li>' + htmlItem + '</li>');
    }
    flush();
    return out;
  }

export { render as renderMarkdown, esc as escapeHtml };
