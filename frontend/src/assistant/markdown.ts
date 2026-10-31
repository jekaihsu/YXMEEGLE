import remarkGfm from 'remark-gfm';
import remarkCjkFriendly from 'remark-cjk-friendly/parseOnly';
import remarkCjkStrikethrough from 'remark-cjk-friendly-gfm-strikethrough/parseOnly';
import type {Root,RootContent} from 'mdast';

function remarkMultiplication(){
 return (tree:Root,file:{value:unknown})=>{
  const source=String(file.value);
  function visit(parent:{children:RootContent[]}){
   parent.children=parent.children.map(node=>{
    const start=node.position?.start.offset,end=node.position?.end.offset;
    if(node.type==='emphasis'&&start!==undefined&&end!==undefined&&/^\*\d+\*$/.test(source.slice(start,end))&&/\d/.test(source[start-1]||'')&&/\d/.test(source[end]||''))return {type:'text',value:source.slice(start,end)};
    if('children' in node)visit(node);
    return node;
   });
  }
  visit(tree);
 };
}
export const assistantRemarkPlugins=[remarkGfm,remarkCjkFriendly,remarkCjkStrikethrough,remarkMultiplication];
