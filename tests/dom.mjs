import { Window } from 'happy-dom';
export const browser = new Window({url:'http://localhost/'});
for (const name of ['window','document','customElements','HTMLElement','Element','Node','ShadowRoot','Document','DocumentFragment','CSSStyleSheet','HTMLDialogElement','HTMLFormElement','FormData','Event','CustomEvent','MouseEvent','KeyboardEvent','MutationObserver','CSS','navigator','getComputedStyle','requestAnimationFrame','cancelAnimationFrame']) {
  const value = name === 'window' ? browser : browser[name];
  Object.defineProperty(globalThis,name,{value:typeof value === 'function' && ['getComputedStyle','requestAnimationFrame','cancelAnimationFrame'].includes(name) ? value.bind(browser) : value,configurable:true,writable:true});
}
export const tick = () => new Promise(resolve => setTimeout(resolve, 0));
